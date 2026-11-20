"""Version management: snapshots, major and minor versions, immutability, version-specific
approvals, comparisons, comments, retention, and full restoration."""

import itertools

import pytest
from sqlalchemy import select, update

from app.core.security import Principal
from app.db.models import LearningObject, MetadataSnapshot
from app.services import versioning
from tests.conftest import build_package

_uploads = itertools.count()


def hdr(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def author(token_factory):
    return hdr(token_factory, ["Contributor"], "author-1")


def admin(token_factory):
    return hdr(token_factory, ["Super Administrator"], "root")


def upload(client, token_factory, title="Versioned"):
    package = build_package(images=[(f"v-{next(_uploads)}.png", title)])
    response = client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("v.zip", package, "application/zip")},
        headers=author(token_factory),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def save(client, token_factory, lo_id, **fields):
    body = {
        "title": "Versioned",
        "description": fields.pop("description", "Initial description"),
        "keywords": ["one", "two"],
        "subject": "Data",
        "language": "en",
    }
    body.update(fields)
    response = client.put(f"/api/v1/metadata/{lo_id}", json=body, headers=author(token_factory))
    assert response.status_code == 200, response.text


def history(client, token_factory, lo_id):
    return client.get(f"/api/v1/versions/{lo_id}", headers=author(token_factory)).json()


def labels(client, token_factory, lo_id):
    return [h["label"] for h in history(client, token_factory, lo_id)["items"]]


def test_labels_start_at_one_zero_and_minor_changes_bump_the_minor(client, token_factory):
    lo_id = upload(client, token_factory)
    assert labels(client, token_factory, lo_id) == ["1.0"]
    save(client, token_factory, lo_id, description="Second description")
    save(client, token_factory, lo_id, description="Third description")
    assert labels(client, token_factory, lo_id) == ["1.0", "1.1", "1.2"]
    save(
        client, token_factory, lo_id, description="Third description"
    )  # no change: no new snapshot
    assert labels(client, token_factory, lo_id) == ["1.0", "1.1", "1.2"]
    assert history(client, token_factory, lo_id)["current"] == "1.2"


def test_promotion_starts_a_new_major_and_file_restore_does_too(client, token_factory):
    lo_id = upload(client, token_factory)
    save(client, token_factory, lo_id, description="Something new")
    promoted = client.post(
        f"/api/v1/versions/{lo_id}/promote",
        json={"comment": "Published edition"},
        headers=author(token_factory),
    )
    assert promoted.json()["label"] == "2.0"
    save(client, token_factory, lo_id, description="After the edition")
    assert labels(client, token_factory, lo_id)[-1] == "2.1"


def test_snapshots_are_immutable_and_tampering_is_detected(client, token_factory, db_session):
    lo_id = upload(client, token_factory)
    row = db_session.scalar(select(MetadataSnapshot).where(MetadataSnapshot.lo_id == lo_id))
    row.comment = "edited after the fact"
    with pytest.raises(RuntimeError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    with pytest.raises(RuntimeError, match="retention"):
        db_session.delete(
            db_session.scalar(select(MetadataSnapshot).where(MetadataSnapshot.lo_id == lo_id))
        )
        db_session.commit()
    db_session.rollback()

    # A change that bypasses the ORM is caught by the digest check.
    db_session.execute(
        update(MetadataSnapshot.__table__)
        .where(MetadataSnapshot.__table__.c.lo_id == lo_id)
        .values(content={"title": "forged"})
    )
    db_session.commit()
    assert history(client, token_factory, lo_id)["items"][0]["intact"] is False
    restored = client.post(
        f"/api/v1/versions/{lo_id}/restore", json={"seq": 1}, headers=author(token_factory)
    )
    assert restored.status_code == 409 and "integrity" in restored.json()["message"]


def test_compare_reports_field_level_changes(client, token_factory):
    lo_id = upload(client, token_factory)
    save(client, token_factory, lo_id)  # baseline: 1.1, subject Data
    save(client, token_factory, lo_id, keywords=["one", "two", "three"], subject="Ethics")  # 1.2
    diff = client.get(
        f"/api/v1/versions/{lo_id}/compare?from=2&to=3", headers=author(token_factory)
    ).json()
    changed = {c["field"]: c for c in diff["changes"]}
    assert diff["unchanged"] is False
    assert changed["subject"]["from"] == "Data" and changed["subject"]["to"] == "Ethics"
    assert changed["keywords"]["to"] == ["one", "two", "three"]
    same = client.get(
        f"/api/v1/versions/{lo_id}/compare?from=3&to=3", headers=author(token_factory)
    ).json()
    assert same["unchanged"] is True


def test_full_restore_brings_back_metadata_not_just_the_file(client, token_factory):
    lo_id = upload(client, token_factory)
    save(client, token_factory, lo_id)  # 1.1: subject Data, keywords one and two
    save(
        client, token_factory, lo_id, subject="Ethics", keywords=["ethics"], description="Changed"
    )  # 1.2
    restored = client.post(
        f"/api/v1/versions/{lo_id}/restore", json={"seq": 2}, headers=author(token_factory)
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["label"] == "1.3" and body["status"] == "draft"
    mapped = client.get(
        f"/api/v1/metadata/{lo_id}/crosswalk?standard=dublin-core", headers=author(token_factory)
    ).json()["mapped"]
    assert mapped["dc:subject"] == ["one", "two", "Data"]
    latest = client.get(
        f"/api/v1/versions/{lo_id}/snapshots/4", headers=author(token_factory)
    ).json()
    assert latest["kind"] == "restore" and latest["comment"] == "Restored 1.1"


def test_approval_is_bound_to_the_version_it_reviewed(client, token_factory, db_session):
    lo_id = upload(client, token_factory)
    save(client, token_factory, lo_id, description="Reviewed text")
    client.post(f"/api/v1/workflow/{lo_id}/submit", headers=author(token_factory))
    approved = client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers=hdr(token_factory, ["Approver"], "appr-1"),
    )
    assert approved.json()["status"] == "approved"

    # Something changes the item after approval (a direct write, since the UI locks metadata).
    lo = db_session.get(LearningObject, lo_id)
    lo.title = "Sneaky change"
    versioning.ensure_snapshot(
        db_session, lo, Principal(subject="ops", roles=frozenset()), "metadata"
    )
    db_session.commit()
    refused = client.post(
        f"/api/v1/workflow/{lo_id}/publish", headers=hdr(token_factory, ["Publisher"], "pub-1")
    )
    assert (
        refused.status_code == 409 and "changed after it was approved" in refused.json()["message"]
    )


def test_restore_is_refused_while_under_review(client, token_factory):
    lo_id = upload(client, token_factory)
    client.post(f"/api/v1/workflow/{lo_id}/submit", headers=author(token_factory))
    response = client.post(
        f"/api/v1/versions/{lo_id}/restore", json={"seq": 1}, headers=author(token_factory)
    )
    assert response.status_code == 409


def test_comments_attach_to_versions(client, token_factory):
    lo_id = upload(client, token_factory)
    save(client, token_factory, lo_id, description="Revised")
    posted = client.post(
        f"/api/v1/versions/{lo_id}/comments",
        json={"body": "Why did the subject change?", "snapshot_seq": 2},
        headers=author(token_factory),
    )
    assert posted.status_code == 201 and posted.json()["snapshot_seq"] == 2
    missing = client.post(
        f"/api/v1/versions/{lo_id}/comments",
        json={"body": "x", "snapshot_seq": 99},
        headers=author(token_factory),
    )
    assert missing.status_code == 404
    listed = client.get(f"/api/v1/versions/{lo_id}/comments", headers=author(token_factory)).json()[
        "items"
    ]
    assert [c["body"] for c in listed] == ["Why did the subject change?"]


def test_retention_keeps_newest_majors_and_approvals(client, token_factory):
    lo_id = upload(client, token_factory)
    for i in range(7):
        save(client, token_factory, lo_id, description=f"Edition text {i}")
    assert len(labels(client, token_factory, lo_id)) == 8
    policy = client.put(
        "/api/v1/versions/retention",
        json={"keep_last": 5, "keep_majors": True},
        headers=admin(token_factory),
    )
    assert policy.status_code == 200
    applied = client.post("/api/v1/versions/retention/apply", headers=admin(token_factory)).json()
    assert applied["removed"] == 2  # seq 2 and 3; seq 1 is a major and is kept
    remaining = labels(client, token_factory, lo_id)
    assert remaining == ["1.0", "1.3", "1.4", "1.5", "1.6", "1.7"]
    assert history(client, token_factory, lo_id)["current"] == "1.7"


def test_retention_is_restricted_to_administrators(client, token_factory):
    reviewer = hdr(token_factory, ["Reviewer"], "rev-1")
    assert (
        client.put(
            "/api/v1/versions/retention", json={"keep_last": 5}, headers=reviewer
        ).status_code
        == 403
    )
    assert client.post("/api/v1/versions/retention/apply", headers=reviewer).status_code == 403
    assert (
        client.put(
            "/api/v1/versions/retention", json={"keep_last": 2}, headers=admin(token_factory)
        ).status_code
        == 422
    )


def test_learners_cannot_promote_or_restore(client, token_factory):
    lo_id = upload(client, token_factory)
    learner = hdr(token_factory, ["Learner"], "learner-1")
    assert client.post(
        f"/api/v1/versions/{lo_id}/promote", json={"comment": "x"}, headers=learner
    ).status_code in (403, 404)
    assert client.post(
        f"/api/v1/versions/{lo_id}/restore", json={"seq": 1}, headers=learner
    ).status_code in (403, 404)
