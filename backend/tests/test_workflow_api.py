"""Phase 4: upload, metadata, submit, approve, publish; illegal transitions; search."""

import pytest

from app.services.workflow import can_transition
from tests.conftest import build_package

CONTRIB = {"sub": "contrib-1", "roles": ["Contributor"]}


def _headers(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def _upload(client, token_factory, title="Data Basics"):
    package = build_package(images=[("a.png", "Chart")], license_text="CC-BY-4.0")
    return client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("course.zip", package, "application/zip")},
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )


def test_upload_submit_approve_publish_happy_path(client, token_factory):
    created = _upload(client, token_factory)
    assert created.status_code == 201, created.text
    body = created.json()
    lo_id = body["id"]
    assert body["status"] == "draft"
    assert body["versions"][0]["version_number"] == 1

    meta = {
        "title": "Data Basics",
        "description": "Intro to data literacy",
        "language": "en",
        "keywords": ["data", "analytics"],
        "subject": "data-literacy",
        "learning_resource_type": "course",
        "license": "CC-BY-4.0",
        "alt_text_provided": True,
    }
    put = client.put(
        f"/api/v1/metadata/{lo_id}",
        json=meta,
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    assert put.status_code == 200, put.text

    submitted = client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    assert submitted.json()["status"] == "submitted"

    approved = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve", "comment": "Looks good"},
        headers=_headers(token_factory, ["Approver", "Publisher", "Reviewer"], "reviewer-1"),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    published = client.post(
        f"/api/v1/workflow/{lo_id}/publish",
        headers=_headers(token_factory, ["Approver", "Publisher", "Reviewer"], "reviewer-1"),
    )
    assert published.json()["status"] == "published"

    # Published items are visible to learners and searchable by facet.
    found = client.get(
        "/api/v1/search",
        params={"q": "data", "subject": "data-literacy"},
        headers=_headers(token_factory, ["Learner"], "learner-1"),
    )
    assert found.status_code == 200
    assert found.json()["total"] == 1
    assert found.json()["items"][0]["id"] == lo_id
    assert found.json()["facets"]["subject"][0]["value"] == "data-literacy"


def test_illegal_transition_is_rejected(client, token_factory):
    lo_id = _upload(client, token_factory).json()["id"]
    # draft -> approved skips submission; must be rejected with 409.
    response = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers=_headers(token_factory, ["Super Administrator"], "reviewer-1"),
    )
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_transition"


def test_reviewer_cannot_decide_on_own_submission(client, token_factory):
    lo_id = _upload(client, token_factory).json()["id"]
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    response = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {token_factory(['Approver'], sub='contrib-1')}"},
    )
    assert response.status_code == 403


def test_reject_requires_comment(client, token_factory):
    lo_id = _upload(client, token_factory).json()["id"]
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    response = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "reject"},
        headers=_headers(token_factory, ["Approver", "Publisher", "Reviewer"], "reviewer-1"),
    )
    assert response.status_code == 422


def test_learner_cannot_see_drafts(client, token_factory):
    lo_id = _upload(client, token_factory).json()["id"]
    response = client.get(
        f"/api/v1/content/{lo_id}",
        headers=_headers(token_factory, ["Learner"], "learner-1"),
    )
    assert response.status_code == 404


def test_metadata_locked_after_approval(client, token_factory):
    lo_id = _upload(client, token_factory).json()["id"]
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers=_headers(token_factory, ["Approver", "Publisher", "Reviewer"], "reviewer-1"),
    )
    response = client.put(
        f"/api/v1/metadata/{lo_id}",
        json={"title": "Changed"},
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    assert response.status_code == 409


def test_upload_rejects_unsupported_extension(client, token_factory):
    response = client.post(
        "/api/v1/content",
        data={"title": "Bad"},
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    assert response.status_code == 400


def test_completions_report_requires_admin(client, token_factory):
    forbidden = client.get(
        "/api/v1/reports/completions",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    assert forbidden.status_code == 403
    allowed = client.get(
        "/api/v1/reports/completions",
        headers=_headers(token_factory, ["Admin"], "admin-1"),
    )
    assert allowed.status_code == 200
    assert allowed.json()["total_completions"] == 0


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ("draft", "submitted", True),
        ("submitted", "approved", True),
        ("submitted", "rejected", True),
        ("approved", "published", True),
        ("rejected", "draft", True),
        ("draft", "approved", False),
        ("draft", "published", False),
        ("published", "draft", False),
        ("approved", "draft", False),
    ],
)
def test_transition_table(current, target, expected):
    assert can_transition(current, target) is expected


def test_admin_can_approve_own_submission(client, token_factory):
    lo_id = _upload(client, token_factory, title="Admin course").json()["id"]
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        headers=_headers(token_factory, ["Contributor"], "contrib-1"),
    )
    # Same subject submitted and approves, but holds the Admin role, so this is allowed.
    response = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {token_factory(['Admin'], sub='contrib-1')}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
