"""Content library: rich text, quizzes, autosave, lifecycle, search, and previews."""

import pytest

from app.services.rich_text import plain_text, sanitize_html

CREATOR = ["Content Creator"]
LEARNER = ["Learner"]
OTHER = "creator-2"


def auth(factory, roles, sub="creator-1"):
    return {"Authorization": "Bearer " + factory(roles, sub=sub)}


def rich(client, headers, title="Photosynthesis notes", html="<p>Chlorophyll absorbs light</p>"):
    response = client.post(
        "/api/v1/library/rich-text",
        json={"title": title, "html": html, "description": "Plant biology", "keywords": ["bio"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def quiz(client, headers, kind="quiz", questions=None):
    questions = questions or [
        {"prompt": "2+2?", "options": ["3", "4"], "correct": 1, "points": 2, "explanation": "Math"},
        {"prompt": "Sky is blue", "type": "true_false", "correct": 0},
    ]
    response = client.post(
        "/api/v1/library/quizzes",
        json={"title": "Arithmetic check", "kind": kind, "questions": questions},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_sanitizer_removes_scripts_handlers_and_unsafe_links():
    dirty = (
        '<p onclick="x">Hi <script>alert(1)</script><b>bold</b>'
        '<a href="javascript:bad()">no</a><a href="https://example.org">ok</a>'
        '<img src=x onerror=y><iframe src="evil"></iframe></p>'
    )
    clean = sanitize_html(dirty)
    assert "script" not in clean and "onclick" not in clean and "onerror" not in clean
    assert "javascript" not in clean and "iframe" not in clean
    assert '<a href="https://example.org" rel="noopener noreferrer">ok</a>' in clean
    assert "<b>bold</b>" in clean and "Hi " in clean
    assert plain_text("<p>a &amp; b</p><style>x</style>c") == "a & b c"


def test_rich_text_is_sanitized_on_create_and_searchable_by_body_text(client, token_factory):
    headers = auth(token_factory, CREATOR)
    item = rich(
        client, headers, html='<p onclick="z">Chlorophyll absorbs light</p><script>no</script>'
    )
    detail = client.get(f"/api/v1/library/{item['id']}", headers=headers).json()
    assert "onclick" not in detail["body"]["html"] and "script" not in detail["body"]["html"]
    # "chlorophyll" appears only in the body, not the title: full-text matching must find it.
    found = client.get("/api/v1/library?q=chlorophyll", headers=headers).json()
    assert [row["id"] for row in found["items"]] == [item["id"]]


def test_quiz_validation_and_answer_visibility(client, token_factory):
    creator = auth(token_factory, CREATOR)
    bad = client.post(
        "/api/v1/library/quizzes",
        json={"title": "x", "questions": [{"prompt": "p", "options": ["a", "b"], "correct": 5}]},
        headers=creator,
    )
    assert bad.status_code == 422
    item = quiz(client, creator)
    as_author = client.get(f"/api/v1/library/{item['id']}", headers=creator).json()
    assert as_author["body"]["questions"][0]["correct"] == 1
    tf = as_author["body"]["questions"][1]
    assert tf["options"] == ["True", "False"]
    # A learner who can read the item never receives the answer key.
    learner = auth(token_factory, LEARNER, sub="learner-1")
    shared = client.get(f"/api/v1/library/{item['id']}", headers=learner)
    assert shared.status_code == 404  # private to its creator until it is shared
    preview = client.get(f"/api/v1/library/{item['id']}/preview", headers=creator).json()
    assert preview["answers_visible"] is True and preview["total_points"] == 3


def test_autosave_rejects_stale_revisions_and_non_authored_kinds(client, token_factory):
    headers = auth(token_factory, CREATOR)
    item = rich(client, headers)
    first = client.put(
        f"/api/v1/library/{item['id']}/draft",
        json={"revision": 1, "html": "<p>v2</p>"},
        headers=headers,
    )
    assert first.status_code == 200 and first.json()["revision"] == 2
    stale = client.put(
        f"/api/v1/library/{item['id']}/draft",
        json={"revision": 1, "html": "<p>from another tab</p>"},
        headers=headers,
    )
    assert stale.status_code == 409
    assert "current revision is 2" in stale.json()["message"]
    detail = client.get(f"/api/v1/library/{item['id']}", headers=headers).json()
    assert detail["body"]["html"] == "<p>v2</p>"
    wrong_field = client.put(
        f"/api/v1/library/{item['id']}/draft",
        json={"revision": 2, "questions": []},
        headers=headers,
    )
    assert wrong_field.status_code == 400


def test_archive_hides_from_others_and_delete_hides_from_everyone(client, token_factory):
    owner = auth(token_factory, CREATOR, sub="creator-1")
    other = auth(token_factory, CREATOR, sub=OTHER)
    item = rich(client, owner, title="Archive me")
    assert client.post(f"/api/v1/library/{item['id']}/archive", headers=owner).status_code == 200
    assert client.get(f"/api/v1/library/{item['id']}", headers=other).status_code == 404
    assert client.get(f"/api/v1/library/{item['id']}", headers=owner).status_code == 200
    owner_archived = client.get("/api/v1/library?state=archived", headers=owner).json()
    assert [r["id"] for r in owner_archived["items"]] == [item["id"]]
    assert client.get("/api/v1/library", headers=owner).json()["total"] == 0

    assert client.delete(f"/api/v1/library/{item['id']}", headers=owner).status_code == 200
    assert client.get(f"/api/v1/library/{item['id']}", headers=owner).status_code == 404
    assert client.get("/api/v1/library?state=archived", headers=owner).json()["total"] == 0
    deleted = client.get("/api/v1/library?state=deleted", headers=owner).json()
    assert [r["id"] for r in deleted["items"]] == [item["id"]]


def test_restore_returns_item_and_rejects_items_not_deleted(client, token_factory):
    owner = auth(token_factory, CREATOR)
    item = rich(client, owner, title="Restore me")
    assert client.post(f"/api/v1/library/{item['id']}/restore", headers=owner).status_code == 409
    client.delete(f"/api/v1/library/{item['id']}", headers=owner)
    restored = client.post(f"/api/v1/library/{item['id']}/restore", headers=owner)
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert client.get(f"/api/v1/library/{item['id']}", headers=owner).status_code == 200


def test_duplicate_copies_body_and_is_not_a_template(client, token_factory):
    owner = auth(token_factory, CREATOR)
    item = quiz(client, owner, kind="assessment")
    client.put(
        f"/api/v1/library/{item['id']}/draft",
        json={"revision": 1, "is_template": True},
        headers=owner,
    )
    copy = client.post(f"/api/v1/library/{item['id']}/duplicate", headers=owner).json()
    assert copy["id"] != item["id"]
    assert copy["title"] == "Copy of Arithmetic check"
    assert copy["is_template"] is False and copy["kind"] == "assessment"
    original = client.get(f"/api/v1/library/{item['id']}", headers=owner).json()
    duplicate = client.get(f"/api/v1/library/{copy['id']}", headers=owner).json()
    assert duplicate["body"]["questions"] == original["body"]["questions"]


def test_templates_are_listed_separately(client, token_factory):
    owner = auth(token_factory, CREATOR)
    template = client.post(
        "/api/v1/library/rich-text",
        json={"title": "Lesson template", "html": "<h1>Objectives</h1>", "is_template": True},
        headers=owner,
    ).json()
    rich(client, owner, title="Not a template")
    listed = client.get("/api/v1/library?template=true", headers=owner).json()
    assert [r["id"] for r in listed["items"]] == [template["id"]]


def test_bulk_actions_report_per_item_results_and_cap_size(client, token_factory):
    owner = auth(token_factory, CREATOR)
    mine = rich(client, owner, title="Mine")
    response = client.post(
        "/api/v1/library/bulk",
        json={"action": "archive", "ids": [mine["id"], "missing-id"]},
        headers=owner,
    ).json()
    by_id = {r["id"]: r for r in response["results"]}
    assert by_id[mine["id"]]["ok"] is True
    assert by_id["missing-id"]["ok"] is False
    assert response["succeeded"] == 1
    too_many = client.post(
        "/api/v1/library/bulk",
        json={"action": "delete", "ids": [f"x{i}" for i in range(101)]},
        headers=owner,
    )
    assert too_many.status_code == 422


def test_learners_cannot_create_or_bulk_edit(client, token_factory):
    learner = auth(token_factory, LEARNER, sub="learner-1")
    create = client.post(
        "/api/v1/library/rich-text", json={"title": "No", "html": ""}, headers=learner
    )
    assert create.status_code == 403
    bulk = client.post(
        "/api/v1/library/bulk", json={"action": "delete", "ids": ["a"]}, headers=learner
    )
    assert bulk.status_code == 403


def test_saved_searches_belong_to_their_owner(client, token_factory):
    owner = auth(token_factory, CREATOR, sub="creator-1")
    other = auth(token_factory, CREATOR, sub=OTHER)
    saved = client.post(
        "/api/v1/library/saved-searches",
        json={"name": "Biology", "params": {"q": "cell", "kind": "rich_text"}},
        headers=owner,
    ).json()
    assert client.get("/api/v1/library/saved-searches", headers=other).json()["items"] == []
    assert (
        client.delete(f"/api/v1/library/saved-searches/{saved['id']}", headers=other).status_code
        == 404
    )
    listed = client.get("/api/v1/library/saved-searches", headers=owner).json()["items"]
    assert listed[0]["params"] == {"q": "cell", "kind": "rich_text"}
    assert (
        client.delete(f"/api/v1/library/saved-searches/{saved['id']}", headers=owner).status_code
        == 204
    )


@pytest.mark.parametrize("state", ["active", "archived", "deleted"])
def test_list_states_accept_only_known_values(client, token_factory, state):
    owner = auth(token_factory, CREATOR)
    assert client.get(f"/api/v1/library?state={state}", headers=owner).status_code == 200
    assert client.get("/api/v1/library?state=bogus", headers=owner).status_code == 422
