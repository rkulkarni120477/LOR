"""Phase 5: xAPI statement endpoint."""

import uuid

from sqlalchemy import select

from app.db.models import XapiStatement

VALID = {
    "actor": {"objectType": "Agent", "mbox": "mailto:learner@example.com"},
    "verb": {"id": "http://adlnet.gov/expapi/verbs/completed", "display": {"en-US": "completed"}},
    "object": {"id": "https://lor.example.com/activities/lo-1", "objectType": "Activity"},
    "result": {"completion": True},
}


def _post(client, token_factory, payload):
    return client.post(
        "/api/v1/xapi/statements",
        json=payload,
        headers={"Authorization": f"Bearer {token_factory(['Learner'], sub='learner-1')}"},
    )


def test_valid_statement_is_stored_and_id_returned(client, token_factory, db_session):
    response = _post(client, token_factory, VALID)
    assert response.status_code == 200, response.text
    ids = response.json()["ids"]
    assert len(ids) == 1
    stored = db_session.get(XapiStatement, ids[0])
    assert stored is not None
    assert stored.actor_key == "mailto:learner@example.com"
    assert stored.verb_id == "http://adlnet.gov/expapi/verbs/completed"


def test_list_of_statements_is_accepted(client, token_factory, db_session):
    second = {**VALID, "object": {"id": "https://lor.example.com/activities/lo-2"}}
    response = _post(client, token_factory, [VALID, second])
    assert response.status_code == 200
    assert len(response.json()["ids"]) == 2
    rows = db_session.scalars(select(XapiStatement)).all()
    assert len(rows) == 2


def test_statement_with_given_uuid_is_kept(client, token_factory, db_session):
    given = str(uuid.uuid4())
    response = _post(client, token_factory, {**VALID, "id": given})
    assert response.json()["ids"] == [given]
    assert db_session.get(XapiStatement, given) is not None


def test_missing_verb_returns_400(client, token_factory):
    bad = {k: v for k, v in VALID.items() if k != "verb"}
    response = _post(client, token_factory, bad)
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_actor_without_identifier_returns_400(client, token_factory):
    bad = {**VALID, "actor": {"objectType": "Agent"}}
    assert _post(client, token_factory, bad).status_code == 400


def test_malformed_json_returns_400(client, token_factory):
    response = client.post(
        "/api/v1/xapi/statements",
        content=b"{not json",
        headers={
            "Authorization": f"Bearer {token_factory(['Learner'])}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_empty_list_returns_400(client, token_factory):
    assert _post(client, token_factory, []).status_code == 400


def test_duplicate_statement_id_returns_409(client, token_factory):
    given = str(uuid.uuid4())
    assert _post(client, token_factory, {**VALID, "id": given}).status_code == 200
    assert _post(client, token_factory, {**VALID, "id": given}).status_code == 409
