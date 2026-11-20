"""Repository persistence and cross-user permission regression tests."""

from sqlalchemy import func, select

from app.db.models import AuditLog, Download, LearningObject, Version


def headers(factory, roles=None, sub="contrib-1"):
    return {"Authorization": f"Bearer {factory(roles or ['Contributor'], sub=sub)}"}


def test_collection_ownership_order_and_cascade(client, token_factory, seeded_lo, db_session):
    owner = headers(token_factory)
    other = headers(token_factory, sub="other")
    created = client.post("/api/v1/collections", json={"name": "Onboarding"}, headers=owner)
    assert created.status_code == 201
    cid = created.json()["id"]
    path = f"/api/v1/collections/{cid}"
    assert client.get(path, headers=other).status_code == 404
    assert (
        client.put(path + "/items", json={"object_ids": [seeded_lo]}, headers=owner).status_code
        == 200
    )
    assert client.get(path, headers=owner).json()["items"][0]["id"] == seeded_lo
    assert (
        client.put(
            path + "/items", json={"object_ids": [seeded_lo, seeded_lo]}, headers=owner
        ).status_code
        == 422
    )
    assert client.get(path, headers=owner).json()["items"][0]["id"] == seeded_lo
    assert (
        client.put(
            path, json={"name": "Onboarding", "visibility": "public"}, headers=owner
        ).status_code
        == 200
    )
    assert client.put(path + "/items", json={"object_ids": []}, headers=other).status_code == 403
    learner = headers(token_factory, ["Learner"])
    assert client.get(path, headers=learner).json()["items"] == []
    assert (
        client.post("/api/v1/collections", json={"name": "Forbidden"}, headers=learner).status_code
        == 403
    )
    assert client.delete(path, headers=owner).status_code == 200
    assert db_session.get(LearningObject, seeded_lo) is not None
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "collection.delete")
        )
        == 1
    )


def test_favorites_are_personal_and_recheck_visibility(
    client, token_factory, seeded_lo, db_session
):
    owner = headers(token_factory, ["Learner"], "learner-a")
    path = f"/api/v1/favorites/{seeded_lo}"
    assert client.put(path, json={}, headers=owner).status_code == 404
    lo = db_session.get(LearningObject, seeded_lo)
    lo.status = "published"
    db_session.commit()
    for _ in range(2):
        assert client.put(path, json={"folder": "Leadership"}, headers=owner).status_code == 200
    assert client.get("/api/v1/favorites?folder=Leadership", headers=owner).json()["total"] == 1
    assert (
        client.get(
            "/api/v1/favorites", headers=headers(token_factory, ["Learner"], "learner-b")
        ).json()["total"]
        == 0
    )
    assert client.get("/api/v1/favorites?q=unmatched", headers=owner).json()["total"] == 0
    lo.status = "draft"
    db_session.commit()
    assert client.get("/api/v1/favorites", headers=owner).json()["total"] == 0
    assert client.delete(path, headers=owner).status_code == 200
    assert client.get("/api/v1/favorites/folders", headers=owner).json()["items"] == [
        "AI in Education",
        "Leadership",
        "Product Training",
    ]


def test_restore_appends_and_requires_author(client, token_factory, seeded_lo, db_session):
    path = f"/api/v1/content/{seeded_lo}/versions/1/restore"
    assert client.post(path, headers=headers(token_factory, sub="other")).status_code == 403
    assert client.post(path, headers=headers(token_factory, ["Learner"])).status_code == 403
    lo = db_session.get(LearningObject, seeded_lo)
    lo.status = "published"
    db_session.commit()
    original = db_session.scalar(select(Version).where(Version.lo_id == seeded_lo))
    old_hash = original.sha256
    response = client.post(path, headers=headers(token_factory))
    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert [v["version_number"] for v in response.json()["versions"]] == [1, 2]
    db_session.refresh(original)
    assert original.sha256 == old_hash
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "version.restore")
        )
        == 1
    )
    assert (
        client.get("/api/v1/dashboard", headers=headers(token_factory)).json()["storage_bytes"]
        == 10
    )
    lo.status = "submitted"
    db_session.commit()
    assert client.post(path, headers=headers(token_factory)).status_code == 409


def test_download_metrics_and_missing_files(client, token_factory, package_bytes, db_session):
    owner = headers(token_factory)
    response = client.post(
        "/api/v1/content",
        data={"title": "Downloadable"},
        files={"file": ("course.zip", package_bytes, "application/zip")},
        headers=owner,
    )
    assert response.status_code == 201
    lo_id = response.json()["id"]
    path = f"/api/v1/content/{lo_id}/download"
    assert client.get(path, headers=headers(token_factory, ["Learner"])).status_code == 404
    download = client.get(path, headers=owner)
    assert download.status_code == 200
    assert download.content == package_bytes
    assert download.headers["content-disposition"].startswith("attachment;")
    assert client.get(path + "?version=999", headers=owner).status_code == 404
    summary = client.get("/api/v1/dashboard", headers=owner).json()
    assert summary["total"] == 1 and summary["downloads"] == 1
    assert summary["storage_bytes"] == len(package_bytes)
    assert db_session.scalar(select(func.count()).select_from(Download)) == 1
    assert (
        client.get("/api/v1/dashboard", headers=headers(token_factory, ["Learner"])).json()["total"]
        == 0
    )
    assert client.get("/api/v1/dashboard").status_code == 401
