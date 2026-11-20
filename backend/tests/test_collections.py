"""Nested collections, inherited sharing and publishing, duplication, analytics, favorite
collections, folder management, sorting and recent access."""

from app.db.models import Collection, Group, GroupMember, LearningObject, User
from tests.conftest import build_package


def auth(factory, roles=None, sub="owner"):
    return {"Authorization": f"Bearer {factory(roles or ['Contributor'], sub=sub)}"}


def make(client, headers, name, parent=None, visibility="private"):
    body = {"name": name, "visibility": visibility}
    if parent:
        body["parent_id"] = parent
    response = client.post("/api/v1/collections", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_nesting_tree_breadcrumbs_and_cycle_prevention(client, token_factory):
    owner = auth(token_factory)
    root = make(client, owner, "Programme")
    child = make(client, owner, "Module 1", parent=root)
    grandchild = make(client, owner, "Lesson A", parent=child)

    listed = client.get("/api/v1/collections?parent=root", headers=owner).json()
    assert [c["id"] for c in listed["items"]] == [root]
    under_root = client.get(f"/api/v1/collections?parent={root}", headers=owner).json()
    assert [c["id"] for c in under_root["items"]] == [child]

    tree = client.get("/api/v1/collections/tree", headers=owner).json()["items"]
    assert tree[0]["id"] == root and tree[0]["children"][0]["children"][0]["id"] == grandchild

    detail = client.get(f"/api/v1/collections/{grandchild}", headers=owner).json()
    assert [b["name"] for b in detail["breadcrumbs"]] == ["Programme", "Module 1", "Lesson A"]

    # A collection cannot move under its own descendant, or under itself.
    cycle = client.put(
        f"/api/v1/collections/{root}/move", json={"parent_id": grandchild}, headers=owner
    )
    assert cycle.status_code == 400 and "cycle" in cycle.json()["message"]
    assert (
        client.put(
            f"/api/v1/collections/{root}/move", json={"parent_id": root}, headers=owner
        ).status_code
        == 400
    )
    # Moving a leaf to the top level works.
    moved = client.put(
        f"/api/v1/collections/{grandchild}/move", json={"parent_id": None}, headers=owner
    )
    assert moved.status_code == 200 and moved.json()["parent_id"] is None


def test_share_view_and_edit_inherit_down_the_tree(client, token_factory):
    owner = auth(token_factory)
    other = auth(token_factory, sub="colleague")
    root = make(client, owner, "Shared root")
    child = make(client, owner, "Inside", parent=root)
    assert client.get(f"/api/v1/collections/{child}", headers=other).status_code == 404

    grant = client.put(
        f"/api/v1/collections/{root}/shares",
        json={"grantee_type": "user", "grantee_id": "colleague", "permission": "view"},
        headers=owner,
    )
    assert grant.status_code == 200
    # View access on the parent reaches the child.
    assert client.get(f"/api/v1/collections/{child}", headers=other).json()["access"] == "view"
    assert (
        client.put(
            f"/api/v1/collections/{child}/items", json={"object_ids": []}, headers=other
        ).status_code
        == 403
    )

    client.put(
        f"/api/v1/collections/{root}/shares",
        json={"grantee_type": "user", "grantee_id": "colleague", "permission": "edit"},
        headers=owner,
    )
    assert client.get(f"/api/v1/collections/{child}", headers=other).json()["access"] == "edit"
    assert (
        client.put(
            f"/api/v1/collections/{child}/items", json={"object_ids": []}, headers=other
        ).status_code
        == 200
    )
    # Editors still cannot share, publish, move or delete.
    assert client.get(f"/api/v1/collections/{root}/shares", headers=other).status_code == 403
    assert (
        client.put(
            f"/api/v1/collections/{root}/publish", json={"published": True}, headers=other
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/collections/{root}", headers=other).status_code == 403

    client.delete(f"/api/v1/collections/{root}/shares/user/colleague", headers=owner)
    assert client.get(f"/api/v1/collections/{child}", headers=other).status_code == 404


def test_group_share_reaches_members(client, token_factory, db_session):
    owner = auth(token_factory)
    member = auth(token_factory, sub="member-1")
    db_session.add(User(subject="member-1", display_name="Member"))
    db_session.commit()
    group = Group(name="Pilot cohort")
    db_session.add(group)
    db_session.commit()
    user = db_session.query(User).filter_by(subject="member-1").one()
    db_session.add(GroupMember(group_id=group.id, user_id=user.id))
    db_session.commit()

    cid = make(client, owner, "For the cohort")
    assert client.get(f"/api/v1/collections/{cid}", headers=member).status_code == 404
    assert (
        client.put(
            f"/api/v1/collections/{cid}/shares",
            json={"grantee_type": "group", "grantee_id": str(group.id), "permission": "view"},
            headers=owner,
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/collections/{cid}", headers=member).status_code == 200
    assert (
        client.put(
            f"/api/v1/collections/{cid}/shares",
            json={"grantee_type": "group", "grantee_id": "9999", "permission": "view"},
            headers=owner,
        ).status_code
        == 400
    )


def test_publishing_makes_collection_readable_by_all_content_readers(client, token_factory):
    owner = auth(token_factory)
    learner = auth(token_factory, ["Learner"], sub="learner-1")
    cid = make(client, owner, "Public good")
    assert client.get(f"/api/v1/collections/{cid}", headers=learner).status_code == 404
    client.put(f"/api/v1/collections/{cid}/publish", json={"published": True}, headers=owner)
    assert client.get(f"/api/v1/collections/{cid}", headers=learner).json()["access"] == "view"
    client.put(f"/api/v1/collections/{cid}/publish", json={"published": False}, headers=owner)
    assert client.get(f"/api/v1/collections/{cid}", headers=learner).status_code == 404


def test_duplicate_copies_subtree_and_skips_unreadable_items(client, token_factory, db_session):
    owner = auth(token_factory)
    readable = client.post(
        "/api/v1/content",
        data={"title": "Readable"},
        files={"file": ("c.zip", build_package(), "application/zip")},
        headers=owner,
    ).json()["id"]
    hidden = client.post(
        "/api/v1/content",
        data={"title": "Hidden draft"},
        files={"file": ("d.zip", build_package(images=[("z.png", "other")]), "application/zip")},
        headers=auth(token_factory, sub="someone-else"),
    ).json()["id"]
    root = make(client, owner, "Original")
    child = make(client, owner, "Child", parent=root)
    client.put(f"/api/v1/collections/{root}/items", json={"object_ids": [readable]}, headers=owner)
    client.put(f"/api/v1/collections/{child}/items", json={"object_ids": []}, headers=owner)
    # Put the hidden object in directly, as an admin-curated collection could contain it.
    db_session.add(
        __import__("app.db.models", fromlist=["CollectionItem"]).CollectionItem(
            collection_id=root, lo_id=hidden, position=5
        )
    )
    db_session.commit()

    result = client.post(f"/api/v1/collections/{root}/duplicate", headers=owner)
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["collections"] == 2 and body["items"] == 1 and body["skipped_items"] == 1
    copy = client.get(f"/api/v1/collections/{body['id']}", headers=owner).json()
    assert copy["name"] == "Copy of Original" and copy["visibility"] == "private"
    assert [i["id"] for i in copy["items"]] == [readable]
    assert len(copy["children"]) == 1


def test_analytics_are_owner_or_editor_only(client, token_factory, db_session):
    owner = auth(token_factory)
    viewer = auth(token_factory, sub="viewer-1")
    cid = make(client, owner, "Measured")
    client.put(
        f"/api/v1/collections/{cid}/shares",
        json={"grantee_type": "user", "grantee_id": "viewer-1", "permission": "view"},
        headers=owner,
    )
    for _ in range(2):
        client.get(f"/api/v1/collections/{cid}", headers=owner)
    client.get(f"/api/v1/collections/{cid}", headers=viewer)
    stats = client.get(f"/api/v1/collections/{cid}/analytics", headers=owner).json()
    assert stats["views"] == 3 and stats["unique_viewers"] == 2
    assert stats["shares"] == 1 and stats["child_collections"] == 0
    assert stats["views_last_30_days"][0]["count"] == 3
    assert client.get(f"/api/v1/collections/{cid}/analytics", headers=viewer).status_code == 403


def test_deleting_a_parent_removes_its_subtree(client, token_factory, db_session):
    owner = auth(token_factory)
    root = make(client, owner, "Parent")
    child = make(client, owner, "Child", parent=root)
    result = client.delete(f"/api/v1/collections/{root}", headers=owner).json()
    assert result == {"deleted": True, "removed": 2}
    assert db_session.get(Collection, child) is None


def test_favorite_collections_follow_current_access(client, token_factory):
    owner = auth(token_factory)
    reader = auth(token_factory, ["Learner"], sub="reader-1")
    cid = make(client, owner, "Keep handy", visibility="published")
    assert client.put(f"/api/v1/favorites/collections/{cid}", headers=reader).json() == {
        "favorite": True
    }
    assert [
        c["id"] for c in client.get("/api/v1/favorites/collections", headers=reader).json()["items"]
    ] == [cid]
    client.put(f"/api/v1/collections/{cid}/publish", json={"published": False}, headers=owner)
    assert client.get("/api/v1/favorites/collections", headers=reader).json()["items"] == []
    assert client.delete(f"/api/v1/favorites/collections/{cid}", headers=reader).json() == {
        "favorite": False
    }


def test_folder_management_rename_delete_and_protection(
    client, token_factory, seeded_lo, db_session
):
    lo = db_session.get(LearningObject, seeded_lo)
    lo.status = "published"
    db_session.commit()
    learner = auth(token_factory, ["Learner"], sub="fan")
    client.put(f"/api/v1/favorites/{seeded_lo}", json={"folder": "Reading"}, headers=learner)

    created = client.post("/api/v1/favorites/folders", json={"name": "Later"}, headers=learner)
    assert created.status_code == 201
    assert (
        client.post(
            "/api/v1/favorites/folders", json={"name": "Later"}, headers=learner
        ).status_code
        == 409
    )
    renamed = client.put(
        "/api/v1/favorites/folders/Reading", json={"name": "Essays"}, headers=learner
    )
    assert renamed.status_code == 200
    assert client.get("/api/v1/favorites?folder=Essays", headers=learner).json()["total"] == 1
    assert (
        client.put(
            "/api/v1/favorites/folders/Leadership", json={"name": "X"}, headers=learner
        ).status_code
        == 400
    )

    details = client.get("/api/v1/favorites/folders", headers=learner).json()["details"]
    by_name = {d["name"]: d for d in details}
    assert by_name["Essays"]["count"] == 1 and by_name["Later"]["count"] == 0
    assert by_name["Leadership"]["system"] is True

    deleted = client.delete(
        "/api/v1/favorites/folders/Essays?move_to=Later", headers=learner
    ).json()
    assert deleted == {"moved": 1}
    assert client.get("/api/v1/favorites?folder=Later", headers=learner).json()["total"] == 1
    assert client.delete("/api/v1/favorites/folders/Leadership", headers=learner).status_code == 400


def test_favorites_sort_by_title(client, token_factory, seeded_lo, db_session):
    lo = db_session.get(LearningObject, seeded_lo)
    lo.status = "published"
    db_session.commit()
    learner = auth(token_factory, ["Learner"], sub="sorter")
    client.put(f"/api/v1/favorites/{seeded_lo}", json={}, headers=learner)
    ordered = client.get("/api/v1/favorites?sort=title&order=asc", headers=learner).json()
    assert ordered["total"] == 1


def test_collections_list_sorts_by_name_and_item_count(client, token_factory):
    owner = auth(token_factory)
    make(client, owner, "Bravo")
    make(client, owner, "alpha")
    names = [
        c["name"]
        for c in client.get("/api/v1/collections?sort=name&order=asc", headers=owner).json()[
            "items"
        ]
    ]
    assert names == ["alpha", "Bravo"]
    desc = [
        c["name"]
        for c in client.get("/api/v1/collections?sort=name&order=desc", headers=owner).json()[
            "items"
        ]
    ]
    assert desc == ["Bravo", "alpha"]
    paged = client.get("/api/v1/collections?sort=items&page=2&page_size=1", headers=owner).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1


def test_recent_access_tracks_collections_and_objects(client, token_factory):
    owner = auth(token_factory)
    cid = make(client, owner, "Opened often")
    client.get(f"/api/v1/collections/{cid}", headers=owner)
    uploaded = client.post(
        "/api/v1/content",
        data={"title": "Recent doc"},
        files={"file": ("r.zip", build_package(), "application/zip")},
        headers=owner,
    ).json()["id"]
    client.get(f"/api/v1/content/{uploaded}", headers=owner)
    items = client.get("/api/v1/recent?limit=5", headers=owner).json()["items"]
    kinds = {(i["kind"], i["title"]) for i in items}
    assert ("collection", "Opened often") in kinds and ("object", "Recent doc") in kinds
    assert items[0]["title"] == "Recent doc"  # most recent first
