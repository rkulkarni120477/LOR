"""Webhooks, branding, content bundles, and AI-assisted authoring with human review."""

import hashlib
import hmac
import io
import itertools
import json
import zipfile

import httpx

from app.db.models import WebhookDelivery
from app.services import ai_authoring, integrations
from tests.conftest import build_package

_uploads = itertools.count()
PUBLIC_IP_URL = "https://93.184.216.34/hook"  # a public address literal: no DNS needed


def hdr(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def admin(token_factory, sub="root"):
    return hdr(token_factory, ["Super Administrator"], sub)


def author(token_factory, sub="author-1"):
    return hdr(token_factory, ["Contributor"], sub)


def upload(client, token_factory, title="Integrated item"):
    package = build_package(images=[(f"int-{next(_uploads)}.png", title)])
    response = client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("i.zip", package, "application/zip")},
        headers=author(token_factory),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- webhooks -------------------------------------------------------------------------------------


def test_webhook_urls_must_be_https_and_not_private(client, token_factory):
    headers = admin(token_factory)
    plain = client.post(
        "/api/v1/integrations/webhooks",
        headers=headers,
        json={"name": "x", "url": "http://93.184.216.34/h", "events": ["*"]},
    )
    assert plain.status_code == 400 and "https" in plain.json()["message"]
    private = client.post(
        "/api/v1/integrations/webhooks",
        headers=headers,
        json={"name": "x", "url": "https://10.0.0.5/h", "events": ["*"]},
    )
    assert private.status_code == 400 and "private" in private.json()["message"]
    creds = client.post(
        "/api/v1/integrations/webhooks",
        headers=headers,
        json={"name": "x", "url": "https://u:p@93.184.216.34/h", "events": ["*"]},
    )
    assert creds.status_code == 400


def test_webhook_is_signed_and_retries_are_bounded(client, token_factory, db_session, settings):
    created = client.post(
        "/api/v1/integrations/webhooks",
        headers=admin(token_factory),
        json={"name": "LMS", "url": PUBLIC_IP_URL, "events": ["content.create"]},
    ).json()
    secret = created["secret"]
    assert (
        "secret"
        not in client.get("/api/v1/integrations/webhooks", headers=admin(token_factory)).json()[
            "items"
        ][0]
    )
    upload(client, token_factory, title="Signed upload")
    queued = db_session.query(WebhookDelivery).filter_by(event="content.create").all()
    assert queued and all(d.status == "pending" for d in queued)

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    result = integrations.dispatch(db_session, settings, transport=httpx.MockTransport(handler))
    assert result["delivered"] >= 1
    request = seen[0]
    header = request.headers["X-ELOR-Signature"]
    timestamp = int(header.split(",")[0].split("=")[1])
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + request.content, hashlib.sha256
    ).hexdigest()
    assert header.endswith(expected)
    assert request.headers["X-ELOR-Event"] == "content.create"
    body = json.loads(request.content)
    assert body["event"] == "content.create" and body["entity_type"] == "learning_object"

    # A failing endpoint gives up after the retry limit instead of retrying forever.
    upload(client, token_factory, title="Failing upload")
    failing = httpx.MockTransport(lambda r: httpx.Response(500))
    for _ in range(integrations.MAX_ATTEMPTS + 1):
        integrations.dispatch(db_session, settings, transport=failing)
    last = db_session.query(WebhookDelivery).filter_by(status="failed").first()
    assert last is not None and last.attempts == integrations.MAX_ATTEMPTS
    assert last.response_code == 500


def test_webhook_events_follow_workflow_and_can_be_disabled(client, token_factory, db_session):
    created = client.post(
        "/api/v1/integrations/webhooks",
        headers=admin(token_factory),
        json={"name": "Publish feed", "url": PUBLIC_IP_URL, "events": ["workflow.published"]},
    ).json()
    hook_id = created["id"]
    lo_id = upload(client, token_factory, title="Ship me")
    assert db_session.query(WebhookDelivery).filter_by(webhook_id=hook_id).count() == 0
    client.put(
        f"/api/v1/integrations/webhooks/{hook_id}",
        headers=admin(token_factory),
        json={"active": False},
    )
    client.post(f"/api/v1/workflow/{lo_id}/submit", headers=author(token_factory))
    client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers=hdr(token_factory, ["Approver"], "appr-1"),
    )
    client.post(
        f"/api/v1/workflow/{lo_id}/publish", headers=hdr(token_factory, ["Publisher"], "pub-1")
    )
    assert db_session.query(WebhookDelivery).filter_by(webhook_id=hook_id).count() == 0
    client.put(
        f"/api/v1/integrations/webhooks/{hook_id}",
        headers=admin(token_factory),
        json={"active": True},
    )
    upload(client, token_factory, title="After reactivation")
    assert (
        db_session.query(WebhookDelivery).filter_by(webhook_id=hook_id).count() == 0
    )  # only published events


def test_webhook_management_is_admin_only(client, token_factory):
    assert (
        client.get("/api/v1/integrations/webhooks", headers=author(token_factory)).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/integrations/deliveries/dispatch", headers=author(token_factory)
        ).status_code
        == 403
    )


# --- branding ----------------------------------------------------------------------------------------  # noqa: E501


def test_branding_is_public_to_read_and_admin_to_change(client, token_factory):
    public = client.get("/api/v1/branding")
    assert public.status_code == 200 and public.json()["app_name"] == "ELOR"
    assert (
        client.put(
            "/api/v1/branding", json={"app_name": "X"}, headers=author(token_factory)
        ).status_code
        == 403
    )
    updated = client.put(
        "/api/v1/branding",
        headers=admin(token_factory),
        json={
            "app_name": "Academy Repository",
            "primary_color": "#0f8a5f",
            "logo_url": "https://cdn.example.test/logo.png",
        },
    )
    assert updated.status_code == 200 and updated.json()["primary_color"] == "#0f8a5f"
    assert client.get("/api/v1/branding").json()["app_name"] == "Academy Repository"
    assert (
        client.put(
            "/api/v1/branding", headers=admin(token_factory), json={"primary_color": "blue"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/branding",
            headers=admin(token_factory),
            json={"logo_url": "http://insecure.example/logo.png"},
        ).status_code
        == 422
    )


def test_admin_overview_counts(client, token_factory):
    overview = client.get("/api/v1/admin/overview", headers=admin(token_factory))
    assert overview.status_code == 200 and {"users", "webhooks", "pending_ai_suggestions"} <= set(
        overview.json()
    )


# --- content bundles ------------------------------------------------------------------------------


def _bundle(client, token_factory, lo_id):
    response = client.get(f"/api/v1/interop/{lo_id}/bundle", headers=author(token_factory))
    assert response.status_code == 200, response.text
    return response.content


def test_bundle_contains_open_formats_and_round_trips(client, token_factory):
    lo_id = upload(client, token_factory, title="Portable course")
    data = _bundle(client, token_factory, lo_id)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "metadata.json", "dublin-core.xml", "xapi-activity.json"} <= names
        assert any(n.startswith("package/") for n in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "elor-bundle" and manifest["package"]["sha256"]
        assert b"<dc:title>Portable course</dc:title>" in archive.read("dublin-core.xml")
    activity = client.get(
        f"/api/v1/interop/{lo_id}/xapi-activity", headers=author(token_factory)
    ).json()
    assert activity["id"] == f"urn:elor:learning-object:{lo_id}"

    # The same package already exists, so importing the same bundle is refused as a duplicate.
    duplicate = client.post(
        "/api/v1/interop/import",
        headers=author(token_factory),
        files={"bundle": ("b.zip", data, "application/zip")},
    )
    assert duplicate.status_code == 409


def test_tampered_or_unsafe_bundles_are_refused(client, token_factory):
    lo_id = upload(client, token_factory, title="Tamper target")
    data = _bundle(client, token_factory, lo_id)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for name in src.namelist():
            content = src.read(name)
            if name.startswith("package/"):
                content = content + b"tampered"
            dst.writestr(name, content)
    tampered = client.post(
        "/api/v1/interop/import",
        headers=author(token_factory),
        files={"bundle": ("t.zip", out.getvalue(), "application/zip")},
    )
    assert tampered.status_code == 400 and "hash" in tampered.json()["message"]

    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../escape.txt", "x")
        archive.writestr("manifest.json", "{}")
    unsafe = client.post(
        "/api/v1/interop/import",
        headers=author(token_factory),
        files={"bundle": ("e.zip", evil.getvalue(), "application/zip")},
    )
    assert unsafe.status_code == 400 and "unsafe" in unsafe.json()["message"]


# --- AI-assisted authoring -------------------------------------------------------------------------------  # noqa: E501


def rich_item(client, token_factory):
    html = (
        "<h2>Photosynthesis basics</h2><p>Chlorophyll absorbs light energy in the chloroplast. "
        "Plants convert carbon dioxide and water into glucose. Oxygen is released as a by-product.</p>"  # noqa: E501
        "<h3>Why it matters</h3><p>Every food chain starts with photosynthesis in producers. "
        '<img src="leaf.png"></p>'
    )
    response = client.post(
        "/api/v1/library/rich-text",
        headers=author(token_factory),
        json={"title": "Photosynthesis", "html": html, "keywords": []},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def suggest(client, token_factory, lo_id, kinds, sub="author-1"):
    response = client.post(
        f"/api/v1/ai/{lo_id}/suggestions", headers=author(token_factory, sub), json={"kinds": kinds}
    )
    assert response.status_code == 201, response.text
    return {s["kind"]: s for s in response.json()["items"]}


def test_rules_generator_drafts_every_kind_from_the_item(client, token_factory):
    lo_id = rich_item(client, token_factory)
    drafts = suggest(
        client,
        token_factory,
        lo_id,
        ["outline", "objectives", "summary", "quiz", "metadata", "classification", "accessibility"],
    )
    assert drafts["outline"]["payload"]["sections"][0].endswith("Photosynthesis basics")
    assert all(o.startswith("By the end") for o in drafts["objectives"]["payload"]["objectives"])
    assert "Chlorophyll" in drafts["summary"]["payload"]["summary"]
    assert len(drafts["quiz"]["payload"]["questions"]) == 3
    assert drafts["quiz"]["payload"]["questions"][0]["correct"] in range(4)
    assert "chlorophyll" in drafts["metadata"]["payload"]["keywords"]
    checks = {c["key"]: c for c in drafts["accessibility"]["payload"]["checks"]}
    # The rich-text sanitizer removes <img> tags, so the item has no images and the alt-text check passes.  # noqa: E501
    assert checks["alt_text"]["passed"] is True and checks["headings"]["passed"] is True
    assert all(d["generator"] == "rules" and d["status"] == "pending" for d in drafts.values())


def test_suggestions_have_no_effect_until_a_second_person_accepts(client, token_factory):
    lo_id = rich_item(client, token_factory)
    before = client.get(
        f"/api/v1/metadata/{lo_id}/crosswalk?standard=dublin-core", headers=author(token_factory)
    ).json()["mapped"]
    summary = suggest(client, token_factory, lo_id, ["summary"])["summary"]
    after = client.get(
        f"/api/v1/metadata/{lo_id}/crosswalk?standard=dublin-core", headers=author(token_factory)
    ).json()["mapped"]
    assert before == after  # drafting changes nothing

    self_accept = client.post(
        f"/api/v1/ai/suggestions/{summary['id']}/accept", json={}, headers=author(token_factory)
    )
    assert self_accept.status_code == 400 and "second person" in self_accept.json()["message"]

    accepted = client.post(
        f"/api/v1/ai/suggestions/{summary['id']}/accept",
        json={"note": "Good"},
        headers=admin(token_factory, sub="reviewer-root"),
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert accepted.json()["decided_by"] == "reviewer-root"
    described = client.get(
        f"/api/v1/metadata/{lo_id}/crosswalk?standard=dublin-core", headers=author(token_factory)
    ).json()["mapped"]
    assert "Chlorophyll" in described["dc:description"]

    again = client.post(
        f"/api/v1/ai/suggestions/{summary['id']}/accept",
        json={},
        headers=admin(token_factory, sub="other-root"),
    )
    assert again.status_code == 409


def test_rejection_needs_a_note_and_edits_are_kept_and_flagged(client, token_factory):
    lo_id = rich_item(client, token_factory)
    quiz = suggest(client, token_factory, lo_id, ["quiz"])["quiz"]
    edited_payload = {
        "questions": [
            {
                "prompt": "Edited question?",
                "type": "single_choice",
                "options": ["Yes", "No"],
                "correct": 0,
                "points": 1,
                "explanation": "",
            }
        ]
    }
    edited = client.put(
        f"/api/v1/ai/suggestions/{quiz['id']}",
        headers=author(token_factory),
        json={"payload": edited_payload},
    )
    assert edited.status_code == 200 and edited.json()["edited"] is True
    no_note = client.post(
        f"/api/v1/ai/suggestions/{quiz['id']}/reject", json={}, headers=admin(token_factory)
    )
    assert no_note.status_code == 400
    rejected = client.post(
        f"/api/v1/ai/suggestions/{quiz['id']}/reject",
        json={"note": "Not accurate"},
        headers=admin(token_factory, sub="reviewer-2"),
    )
    assert rejected.json()["status"] == "rejected"
    assert (
        client.put(
            f"/api/v1/ai/suggestions/{quiz['id']}",
            headers=author(token_factory),
            json={"payload": {}},
        ).status_code
        == 409
    )


def test_accepted_outline_lands_in_the_body_and_file_items_only_record(client, token_factory):
    lo_id = rich_item(client, token_factory)
    outline = suggest(client, token_factory, lo_id, ["outline"])["outline"]
    client.post(
        f"/api/v1/ai/suggestions/{outline['id']}/accept",
        json={},
        headers=admin(token_factory, sub="reviewer-3"),
    )
    detail = client.get(f"/api/v1/library/{lo_id}", headers=author(token_factory)).json()
    assert "<h2>Outline</h2>" in detail["body"]["html"]

    package_item = upload(client, token_factory, title="Package only")
    file_outline = suggest(client, token_factory, package_item, ["outline"])["outline"]
    accepted = client.post(
        f"/api/v1/ai/suggestions/{file_outline['id']}/accept",
        json={},
        headers=admin(token_factory, sub="reviewer-4"),
    ).json()
    assert accepted["status"] == "accepted" and "recorded only" in accepted["decision_note"]


def test_model_failure_falls_back_to_rules_and_says_so(
    client, token_factory, settings, monkeypatch
):
    settings.ai_authoring_mode = "llm"

    def unavailable(kind, ctx, settings):  # noqa: ANN001
        raise ValueError("model unavailable")

    monkeypatch.setattr(ai_authoring, "llm", unavailable)
    lo_id = rich_item(client, token_factory)
    summary = suggest(client, token_factory, lo_id, ["summary"])["summary"]
    assert summary["generator"] == "rules (fallback)"


def test_learners_cannot_request_or_decide_suggestions(client, token_factory):
    lo_id = rich_item(client, token_factory)
    learner = hdr(token_factory, ["Learner"], "learner-9")
    assert (
        client.post(
            f"/api/v1/ai/{lo_id}/suggestions", headers=learner, json={"kinds": ["summary"]}
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/ai/{lo_id}/suggestions", headers=learner).status_code in (200, 404)


def test_unknown_kinds_are_refused(client, token_factory):
    lo_id = rich_item(client, token_factory)
    response = client.post(
        f"/api/v1/ai/{lo_id}/suggestions", headers=author(token_factory), json={"kinds": ["poetry"]}
    )
    assert response.status_code == 422
