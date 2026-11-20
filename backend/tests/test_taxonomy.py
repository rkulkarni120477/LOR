"""Metadata schema, controlled vocabularies, merging, bulk updates, CSV import/export, quality
scoring and standards crosswalks."""

import itertools

from app.db.models import TaxonomyTerm
from tests.conftest import build_package

ADMIN = {"roles": ["Super Administrator"], "sub": "root"}


def hdr(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def admin(token_factory):
    return hdr(token_factory, ["Super Administrator"], "root")


def author(token_factory):
    return hdr(token_factory, ["Contributor"], "author-1")


_uploads = itertools.count()


def upload(client, token_factory, title="Taxonomy item"):
    # Each package gets unique content, so duplicate detection never interferes with these tests.
    package = build_package(images=[(f"unique-{next(_uploads)}.png", title)])
    response = client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("course.zip", package, "application/zip")},
        headers=author(token_factory),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def put_meta(client, token_factory, lo_id, **fields):
    body = {
        "title": "Taxonomy item",
        "description": "A reasonably long description for scoring.",
        "keywords": ["alpha", "beta", "gamma"],
        "subject": "Data",
        "language": "en",
        "learning_resource_type": "course",
        "license": "CC-BY-4.0",
        "duration": "PT10M",
    }
    body.update(fields)
    return client.put(f"/api/v1/metadata/{lo_id}", json=body, headers=author(token_factory))


def field(client, token_factory, **body):
    response = client.post(
        "/api/v1/metadata/schema/fields", json=body, headers=admin(token_factory)
    )
    assert response.status_code == 201, response.text
    return response.json()


def vocab(client, token_factory, name, locked=False):
    response = client.post(
        "/api/v1/taxonomy/vocabularies",
        json={"name": name, "locked": locked},
        headers=admin(token_factory),
    )
    assert response.status_code == 201, response.text


def term(client, token_factory, name, code, label, parent_code=None):
    body = {"code": code, "label": label}
    if parent_code:
        body["parent_code"] = parent_code
    response = client.post(
        f"/api/v1/taxonomy/vocabularies/{name}/terms", json=body, headers=admin(token_factory)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_custom_fields_are_validated_on_save(client, token_factory):
    field(
        client,
        token_factory,
        key="audience",
        label="Audience",
        field_type="select",
        options=["staff", "students"],
        required=True,
    )
    field(client, token_factory, key="review_date", label="Review date", field_type="date")
    lo_id = upload(client, token_factory)

    missing = put_meta(client, token_factory, lo_id)
    assert missing.status_code == 400 and "Audience is required" in missing.json()["message"]
    wrong = put_meta(client, token_factory, lo_id, custom={"audience": "pets"})
    assert wrong.status_code == 400 and "not an allowed value" in wrong.json()["message"]
    bad_date = put_meta(
        client, token_factory, lo_id, custom={"audience": "staff", "review_date": "soon"}
    )
    assert bad_date.status_code == 400
    unknown = put_meta(client, token_factory, lo_id, custom={"audience": "staff", "colour": "red"})
    assert unknown.status_code == 400 and "unknown custom field" in unknown.json()["message"]

    saved = put_meta(
        client, token_factory, lo_id, custom={"audience": "students", "review_date": "2027-01-15"}
    )
    assert saved.status_code == 200 and saved.json()["custom"]["audience"] == "students"


def test_reserved_and_duplicate_field_keys_are_refused(client, token_factory):
    assert (
        client.post(
            "/api/v1/metadata/schema/fields",
            headers=admin(token_factory),
            json={"key": "subject", "label": "x", "field_type": "text"},
        ).status_code
        == 400
    )
    field(client, token_factory, key="level", label="Level", field_type="text")
    dup = client.post(
        "/api/v1/metadata/schema/fields",
        headers=admin(token_factory),
        json={"key": "level", "label": "Level", "field_type": "text"},
    )
    assert dup.status_code == 409


def test_locked_vocabulary_constrains_subject_and_resource_type(client, token_factory):
    vocab(client, token_factory, "subject", locked=True)
    term(client, token_factory, "subject", "DATA", "Data")
    lo_id = upload(client, token_factory)
    free = put_meta(client, token_factory, lo_id, subject="Gardening")
    assert free.status_code == 400 and "controlled vocabulary" in free.json()["message"]
    assert put_meta(client, token_factory, lo_id, subject="Data").status_code == 200


def test_merging_terms_updates_items_and_moves_children(client, token_factory, db_session):
    vocab(client, token_factory, "topics")
    source = term(client, token_factory, "topics", "AI", "Artificial intelligence")
    target = term(client, token_factory, "topics", "ML", "Machine learning")
    child = term(client, token_factory, "topics", "NLP", "Language", parent_code="AI")
    field(
        client, token_factory, key="topic", label="Topic", field_type="select", vocabulary="topics"
    )

    draft = upload(client, token_factory, title="Draft item")
    put_meta(
        client,
        token_factory,
        draft,
        keywords=["Artificial intelligence", "intro", "artificial intelligence"],
        custom={"topic": "Artificial intelligence"},
    )
    submitted = upload(client, token_factory, title="Submitted item")
    put_meta(client, token_factory, submitted, keywords=["Artificial intelligence"])
    client.post(f"/api/v1/workflow/{submitted}/submit", headers=author(token_factory))

    result = client.post(
        f"/api/v1/taxonomy/terms/{source}/merge",
        json={"into_id": target},
        headers=admin(token_factory),
    ).json()
    # The draft follows the merge. The submitted item is locked, so it is counted as skipped.
    assert result == {"items_updated": 1, "items_skipped": 1, "children_moved": 1}
    rows = {
        i["id"]: i
        for i in client.get(
            "/api/v1/metadata/export?format=json", headers=admin(token_factory)
        ).json()["items"]
    }
    assert rows[draft]["custom"]["topic"] == "Machine learning"
    assert rows[draft]["keywords"] == ["Machine learning", "intro"]  # duplicates folded together
    assert rows[submitted]["keywords"] == ["Artificial intelligence"]  # locked, unchanged
    merged = db_session.get(TaxonomyTerm, source)
    assert merged.status == "merged" and merged.merged_into_id == target
    assert db_session.get(TaxonomyTerm, child).parent_id == target
    active = client.get(
        "/api/v1/taxonomy/vocabularies/topics/terms?status=active", headers=admin(token_factory)
    ).json()["items"]
    assert {t["code"] for t in active} == {"ML", "NLP"}


def test_bulk_update_reports_each_item(client, token_factory):
    draft = upload(client, token_factory, title="Bulk draft")
    put_meta(client, token_factory, draft)
    submitted = upload(client, token_factory, title="Bulk submitted")
    put_meta(client, token_factory, submitted)
    client.post(f"/api/v1/workflow/{submitted}/submit", headers=author(token_factory))

    response = client.post(
        "/api/v1/metadata/bulk-update",
        json={
            "ids": [draft, submitted],
            "changes": {
                "subject": "Leadership",
                "add_keywords": ["strategy"],
                "remove_keywords": ["gamma"],
            },
        },
        headers=admin(token_factory),
    ).json()
    by_id = {r["id"]: r for r in response["results"]}
    assert by_id[draft]["ok"] is True
    assert (
        by_id[submitted]["ok"] is False
        and "metadata cannot be edited" in by_id[submitted]["message"]
    )
    assert response["succeeded"] == 1
    export = client.get("/api/v1/metadata/export?format=json", headers=admin(token_factory)).json()[
        "items"
    ]
    row = next(i for i in export if i["id"] == draft)
    assert (
        row["subject"] == "Leadership"
        and "strategy" in row["keywords"]
        and "gamma" not in row["keywords"]
    )


def test_csv_import_dry_run_then_apply(client, token_factory):
    lo_id = upload(client, token_factory)
    put_meta(client, token_factory, lo_id)
    csv_text = f"id,title,subject,keywords\n{lo_id},Renamed title,Ethics,ethics;policy\n"
    preview = client.post(
        "/api/v1/metadata/import",
        json={"content": csv_text, "dry_run": True},
        headers=admin(token_factory),
    ).json()
    assert preview["dry_run"] is True and preview["succeeded"] == 1
    export = client.get("/api/v1/metadata/export?format=json", headers=admin(token_factory)).json()[
        "items"
    ]
    assert (
        next(i for i in export if i["id"] == lo_id)["subject"] == "Data"
    )  # dry run changed nothing

    applied = client.post(
        "/api/v1/metadata/import",
        json={"content": csv_text, "dry_run": False},
        headers=admin(token_factory),
    ).json()
    assert applied["succeeded"] == 1
    export = client.get("/api/v1/metadata/export?format=json", headers=admin(token_factory)).json()[
        "items"
    ]
    row = next(i for i in export if i["id"] == lo_id)
    assert row["subject"] == "Ethics" and row["keywords"] == ["ethics", "policy"]


def test_csv_import_rejects_bad_headers_and_reports_bad_rows(client, token_factory):
    lo_id = upload(client, token_factory)
    no_id = client.post(
        "/api/v1/metadata/import",
        json={"content": "title\nx\n", "dry_run": True},
        headers=admin(token_factory),
    )
    assert no_id.status_code == 400
    unknown = client.post(
        "/api/v1/metadata/import",
        json={"content": f"id,colour\n{lo_id},red\n", "dry_run": True},
        headers=admin(token_factory),
    )
    assert unknown.status_code == 400
    bad_row = client.post(
        "/api/v1/metadata/import",
        json={"content": "id,title\nnot-a-real-id,x\n", "dry_run": True},
        headers=admin(token_factory),
    ).json()
    assert bad_row["succeeded"] == 0 and bad_row["results"][0]["ok"] is False


def test_export_csv_and_json(client, token_factory):
    field(client, token_factory, key="cohort", label="Cohort", field_type="text")
    lo_id = upload(client, token_factory)
    put_meta(client, token_factory, lo_id, custom={"cohort": "2027A"})
    csv_body = client.get("/api/v1/metadata/export?format=csv", headers=admin(token_factory))
    assert csv_body.status_code == 200 and csv_body.headers["content-type"].startswith("text/csv")
    header = csv_body.text.splitlines()[0].split(",")
    assert header[:2] == ["id", "status"] and "custom.cohort" in header
    assert lo_id in csv_body.text and "2027A" in csv_body.text


def test_vocabulary_csv_round_trip_keeps_hierarchy(client, token_factory):
    vocab(client, token_factory, "domains")
    csv_text = "code,label,parent_code\nSCI,Science,\nBIO,Biology,SCI\n"
    result = client.post(
        "/api/v1/taxonomy/vocabularies/domains/import",
        json={"content": csv_text, "dry_run": False},
        headers=admin(token_factory),
    ).json()
    assert result == {"created": 2, "updated": 0}
    exported = client.get(
        "/api/v1/taxonomy/vocabularies/domains/export", headers=admin(token_factory)
    )
    assert "BIO,Biology,SCI,active" in exported.text


def test_quality_score_rewards_complete_metadata(client, token_factory):
    lo_id = upload(client, token_factory)
    put_meta(client, token_factory, lo_id)
    quality = client.get(f"/api/v1/metadata/{lo_id}/quality", headers=author(token_factory)).json()
    assert quality["score"] >= 70
    assert {c["key"] for c in quality["checks"]} >= {"description", "keywords", "license"}
    sparse = upload(client, token_factory, title="Sparse")
    low = client.get(f"/api/v1/metadata/{sparse}/quality", headers=author(token_factory)).json()
    assert low["score"] < quality["score"] and low["issues"]
    summary = client.get("/api/v1/metadata/quality/summary", headers=admin(token_factory)).json()
    assert summary["items"] >= 2 and summary["below_threshold"] >= 1


def test_dublin_core_crosswalk_maps_fields(client, token_factory):
    field(client, token_factory, key="cohort2", label="Cohort", field_type="text")
    lo_id = upload(client, token_factory)
    put_meta(client, token_factory, lo_id, custom={"cohort2": "A"})
    mapped = client.get(
        f"/api/v1/metadata/{lo_id}/crosswalk?standard=dublin-core", headers=author(token_factory)
    ).json()
    assert mapped["mapped"]["dc:title"] == "Taxonomy item"
    assert mapped["mapped"]["dc:rights"] == "CC-BY-4.0"
    # Keywords and the subject both land on dc:subject, so the list keeps both.
    assert mapped["mapped"]["dc:subject"] == ["alpha", "beta", "gamma", "Data"]
    assert mapped["unmapped_custom_fields"] == ["cohort2"]
    assert (
        client.get(
            f"/api/v1/metadata/{lo_id}/crosswalk?standard=nope", headers=author(token_factory)
        ).status_code
        == 404
    )


def test_learners_and_reviewers_cannot_manage_schema_or_bulk_edit(client, token_factory):
    reviewer = hdr(token_factory, ["Reviewer"], "rev-1")
    assert (
        client.post(
            "/api/v1/metadata/schema/fields",
            headers=reviewer,
            json={"key": "nope", "label": "x", "field_type": "text"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/metadata/bulk-update", headers=reviewer, json={"ids": ["a"], "changes": {}}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/taxonomy/vocabularies", headers=reviewer, json={"name": "sneaky"}
        ).status_code
        == 403
    )
    # Reading the schema and exporting is open to anyone who can read content.
    assert client.get("/api/v1/metadata/schema", headers=reviewer).status_code == 200
