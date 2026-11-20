"""Library acceptance: real persistence, format delivery, scoring and permission failures."""

import base64
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select

from app.db.models import AssessmentAttempt, LearningObject, PackageActivity, PreviewTicket, Version
from tests.test_library import auth, quiz, rich


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, data in files.items():
            package.writestr(name, data)
    return buffer.getvalue()


def upload(client, factory, filename, data):
    response = client.post(
        "/api/v1/content",
        headers=auth(factory, ["Content Creator"]),
        data={"title": filename},
        files={"file": (filename, data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ticket(client, factory, identity):
    response = client.post(
        f"/api/v1/library/{identity}/preview-session", headers=auth(factory, ["Content Creator"])
    )
    assert response.status_code == 200, response.text
    return response.json()["url"].replace("/api/v1", "/api/v1", 1)


def test_advanced_filters_saved_search_and_ordering(client, token_factory):
    owner = auth(token_factory, ["Content Creator"])
    created = client.post(
        "/api/v1/library/rich-text",
        headers=owner,
        json={
            "title": "Alpha discovery",
            "html": "<p>Quasar body search</p>",
            "language": "en",
            "subject": "Science",
            "difficulty": "advanced",
            "duration_minutes": 45,
            "learning_standard": "LOM",
            "keywords": ["astronomy"],
            "description": "Investigate stars",
        },
    )
    assert created.status_code == 201, created.text
    rich(client, owner, title="Zebra training")
    params = {
        "q": "Quasar",
        "language": "en",
        "subject": "Science",
        "difficulty": "advanced",
        "duration_min": 30,
        "duration_max": 60,
        "learning_standard": "LOM",
        "keywords": "astronomy",
    }
    result = client.get("/api/v1/library", headers=owner, params=params)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    assert client.get("/api/v1/library?duration_max=20", headers=owner).json()["total"] == 0
    saved = client.post(
        "/api/v1/library/saved-searches",
        headers=owner,
        json={"name": "Advanced", "params": {k: str(v) for k, v in params.items()}},
    )
    assert saved.status_code == 201
    assert saved.json()["params"]["difficulty"] == "advanced"
    assert (
        client.get("/api/v1/library?sort=title_desc", headers=owner).json()["items"][0]["title"]
        == "Zebra training"
    )


@pytest.mark.parametrize(
    "filename,data,expected",
    [
        (
            "lesson.docx",
            archive(
                {
                    "word/document.xml": (
                        "<document><p><t>Quasar searchable document</t></p></document>"
                    )
                }
            ),
            "document",
        ),
        (
            "slides.pptx",
            archive(
                {
                    "ppt/presentation.xml": "<presentation/>",
                    "ppt/slides/slide1.xml": "<slide><p><t>Quasar searchable slide</t></p></slide>",
                }
            ),
            "document",
        ),
        ("film.mp4", b"\x00\x00\x00\x18ftypisom" + b"0" * 32, "video"),
        ("audio.mp3", b"ID3" + b"0" * 32, "audio"),
        (
            "image.png",
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1sAAAAASUVORK5CYII="
            ),
            "image",
        ),
        (
            "lesson.html",
            b"<!doctype html><h1>Quasar interactive simulation</h1>"
            b"<script>window.example=1</script>",
            "package",
        ),
    ],
)
def test_format_upload_preview_and_byte_ranges(client, token_factory, filename, data, expected):
    identity = upload(client, token_factory, filename, data)
    owner = auth(token_factory, ["Content Creator"])
    response = client.post(f"/api/v1/library/{identity}/preview-session", headers=owner)
    assert response.json()["mode"] == expected
    resource = client.get(response.json()["url"])
    assert resource.status_code == 200, resource.text
    assert "allow-same-origin" not in resource.headers["content-security-policy"]
    if expected == "document":
        assert "Quasar" in resource.text
        assert client.get("/api/v1/library?q=Quasar", headers=owner).json()["total"] == 1
    if expected in {"audio", "video"}:
        partial = client.get(response.json()["url"], headers={"Range": "bytes=0-2"})
        assert partial.status_code == 206 and partial.content == data[:3]
        assert (
            client.get(response.json()["url"], headers={"Range": "bytes=99999-"}).status_code == 416
        )


def test_package_runtime_state_expiry_and_revocation(client, token_factory, db_session):
    identity = upload(
        client,
        token_factory,
        "web.zip",
        archive({"index.html": "<h1>Course</h1>", "assets/app.js": "window.test=1;"}),
    )
    url = ticket(client, token_factory, identity)
    root = urlsplit(url).path.removesuffix("__launch")
    document = client.get(url)
    assert document.status_code == 200 and "API_1484_11" in document.text
    assert client.get(root + "assets/app.js").status_code == 200
    commit = client.post(
        root + "__runtime",
        content=json.dumps({"cmi.suspend_data": "bookmark", "cmi.completion_status": "completed"}),
        headers={"content-type": "text/plain"},
    )
    assert commit.status_code == 200, commit.text
    assert db_session.scalar(select(PackageActivity)).data["cmi.suspend_data"] == "bookmark"
    assert "bookmark" in client.get(url).text
    assert client.post(root + "__runtime", json={"untrusted.admin": True}).status_code == 422
    row = db_session.scalar(select(PreviewTicket))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert client.get(url).status_code == 401
    fresh = ticket(client, token_factory, identity)
    db_session.get(LearningObject, identity).deleted_at = datetime.now(UTC)
    db_session.commit()
    assert client.get(fresh).status_code == 404


def test_h5p_and_missing_libraries(client, token_factory):
    manifest = {
        "title": "H5P",
        "mainLibrary": "H5P.Test",
        "preloadedDependencies": [
            {"machineName": "H5P.Test", "majorVersion": 1, "minorVersion": 0}
        ],
    }
    files = {
        "h5p.json": json.dumps(manifest),
        "content/content.json": "{}",
        "H5P.Test-1.0/library.json": "{}",
    }
    identity = upload(client, token_factory, "lesson.h5p", archive(files))
    assert "H5PStandalone.H5P" in client.get(ticket(client, token_factory, identity)).text
    del files["H5P.Test-1.0/library.json"]
    result = client.post(
        "/api/v1/content",
        headers=auth(token_factory, ["Content Creator"]),
        data={"title": "Missing"},
        files={"file": ("missing.h5p", archive(files), "application/zip")},
    )
    assert result.status_code == 400 and "dependency" in result.text


def test_assessment_score_is_server_calculated_and_history_is_personal(
    client, token_factory, db_session
):
    owner = auth(token_factory, ["Content Creator"])
    item = quiz(client, owner, kind="assessment")
    db_session.get(LearningObject, item["id"]).status = "published"
    db_session.commit()
    learner = auth(token_factory, ["Learner"], sub="learner-1")
    attempt = client.post(
        f"/api/v1/library/{item['id']}/attempts",
        headers=learner,
        json={"revision": 1, "answers": [1, 0]},
    )
    assert (
        attempt.status_code == 201 and attempt.json()["score"] == 100 and attempt.json()["passed"]
    )
    assert db_session.scalar(select(AssessmentAttempt)).actor_subject == "learner-1"
    assert client.get(f"/api/v1/library/{item['id']}/attempts", headers=owner).json()["items"] == []
    assert (
        client.post(
            f"/api/v1/library/{item['id']}/attempts",
            headers=learner,
            json={"revision": 99, "answers": [1, 0]},
        ).status_code
        == 409
    )


def test_replacement_preserves_history_and_rejects_stale_edit(client, token_factory, db_session):
    identity = upload(client, token_factory, "old.html", b"<h1>Original content</h1>")
    owner = auth(token_factory, ["Content Creator"])
    before = db_session.scalar(select(Version).where(Version.lo_id == identity)).sha256
    result = client.post(
        f"/api/v1/library/{identity}/file",
        headers=owner,
        data={"revision": 1},
        files={"file": ("new.html", b"<h1>Replacement content</h1>", "text/html")},
    )
    assert result.status_code == 200, result.text
    db_session.expire_all()
    versions = list(
        db_session.scalars(
            select(Version).where(Version.lo_id == identity).order_by(Version.version_number)
        )
    )
    assert len(versions) == 2 and versions[0].sha256 == before and versions[1].sha256 != before
    assert (
        client.post(
            f"/api/v1/library/{identity}/file",
            headers=owner,
            data={"revision": 1},
            files={"file": ("next.html", b"<h1>Next</h1>", "text/html")},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/library/{identity}/metadata",
            headers=owner,
            json={"revision": 2, "title": "Retitled file"},
        ).status_code
        == 200
    )


def test_builtin_templates_and_incomplete_draft(client, token_factory):
    owner = auth(token_factory, ["Content Creator"])
    catalog = client.get("/api/v1/library/templates/catalog", headers=owner).json()["items"]
    assert {item["kind"] for item in catalog} == {"rich_text", "quiz", "assessment"}
    for template in catalog:
        response = client.post(f"/api/v1/library/templates/{template['key']}", headers=owner)
        assert response.status_code == 201, response.text
        assert response.json()["is_template"] is False
    item = quiz(client, owner)
    saved = client.put(
        f"/api/v1/library/{item['id']}/draft",
        headers=owner,
        json={"revision": 1, "questions": [{"prompt": "", "options": ["", ""], "correct": 0}]},
    )
    assert saved.status_code == 200, saved.text
    from app.core.errors import ValidationFailure
    from app.db.models import LearningObject
    from app.services.library import validate_for_submission

    unfinished = LearningObject(
        kind="quiz", body={"questions": [{"prompt": "", "options": ["", ""], "correct": 0}]}
    )
    with pytest.raises(ValidationFailure):
        validate_for_submission(unfinished)


def test_package_xapi_state_and_statement_conflicts(client, token_factory, db_session):
    identity = upload(client, token_factory, "course.zip", archive({"index.html": "<p>Course</p>"}))
    url = ticket(client, token_factory, identity)
    base = url.rsplit("/", 1)[0] + "/"
    endpoint = base + "__lrs/statements"
    statement = {"id": "test-statement", "verb": {"id": "completed"}, "object": {"id": "lesson"}}
    result = client.post(endpoint, json=statement)
    assert result.status_code == 200, result.text
    assert client.get(endpoint).json()["statements"] == [statement]
    assert client.post(endpoint, json={**statement, "verb": {"id": "changed"}}).status_code == 409
    state = base + "__lrs/activities/state?stateId=progress"
    assert client.put(state, json={"page": 3}).status_code == 204
    assert client.get(state).json() == {"page": 3}
    assert client.options(endpoint).headers["access-control-allow-origin"] == "*"


def test_authored_snapshot_restore_refreshes_search(client, token_factory):
    owner = auth(token_factory, ["Content Creator"])
    item = rich(client, owner, html="<p>Originalquasar</p>")
    changed = client.put(
        f"/api/v1/library/{item['id']}/draft",
        headers=owner,
        json={"revision": 1, "html": "<p>Replacementnebula</p>"},
    )
    assert changed.status_code == 200
    restored = client.post(f"/api/v1/versions/{item['id']}/restore", headers=owner, json={"seq": 1})
    assert restored.status_code == 200, restored.text
    detail = client.get(f"/api/v1/library/{item['id']}", headers=owner).json()
    assert detail["body"]["html"] == "<p>Originalquasar</p>"
    assert detail["revision"] == 3
    assert client.get("/api/v1/library?q=Originalquasar", headers=owner).json()["total"] == 1
    assert client.get("/api/v1/library?q=Replacementnebula", headers=owner).json()["total"] == 0
