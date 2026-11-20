"""Offline tests for the production-service boundaries and transactional outbox."""

from unittest.mock import MagicMock

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import worker
from app.core.config import Settings
from app.db.models import LearningObject, SearchIndexJob
from app.services import search, search_index


def test_outbox_commits_and_rollbacks_with_content(db_session, seeded_lo, monkeypatch):
    monkeypatch.setattr(
        search_index, "get_settings", lambda: Settings(_env_file=None, search_backend="opensearch")
    )
    search_index.schedule_index(db_session, seeded_lo)
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(SearchIndexJob)) == 0
    search_index.schedule_index(db_session, seeded_lo)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(SearchIndexJob)) == 1


def test_worker_retries_failed_index_and_removes_success(
    engine, db_session, seeded_lo, monkeypatch
):
    monkeypatch.setattr(
        worker, "get_settings", lambda: Settings(_env_file=None, search_backend="opensearch")
    )
    monkeypatch.setattr(worker, "get_session_factory", lambda: sessionmaker(bind=engine))
    monkeypatch.setattr(worker, "ensure_index", lambda: None)
    db_session.add(SearchIndexJob(lo_id=seeded_lo))
    db_session.commit()
    projection = MagicMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(worker, "index_object", projection)
    assert worker.process_search_outbox.run() == {"indexed": 0, "failed": 1}
    db_session.expire_all()
    job = db_session.scalar(select(SearchIndexJob))
    assert job.attempts == 1
    from datetime import UTC, datetime, timedelta

    job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    projection.side_effect = None
    assert worker.process_search_outbox.run() == {"indexed": 1, "failed": 0}
    assert db_session.scalar(select(func.count()).select_from(SearchIndexJob)) == 0


def test_index_never_publishes_draft_metadata(db_session, seeded_lo):
    client = MagicMock()
    search_index.index_object(db_session, seeded_lo, client)
    client.index.assert_not_called()
    client.delete.assert_called_once()
    lo = db_session.get(LearningObject, seeded_lo)
    lo.status = "published"
    db_session.commit()
    search_index.index_object(db_session, seeded_lo, client)
    assert client.index.call_args.kwargs["body"]["title"] == lo.title


def test_search_rechecks_publication_even_if_index_is_stale(db_session, seeded_lo, monkeypatch):
    monkeypatch.setattr(
        search, "get_settings", lambda: Settings(_env_file=None, search_backend="opensearch")
    )
    monkeypatch.setattr(search, "matching_ids", lambda _: [seeded_lo])
    hits, total, facets = search.search(
        db_session, q="data", subject=None, format=None, page=1, page_size=20
    )
    assert hits == [] and total == 0 and facets["subject"] == []


def test_readiness_checks_database(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok"}
