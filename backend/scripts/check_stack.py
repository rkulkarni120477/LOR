"""Live stack smoke test with a real Celery worker and broker.

Requires DATABASE_URL to name a disposable *_test database. Does not use application data.
"""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import Principal  # noqa: E402
from app.db.models import LearningObject  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services import content, search, workflow  # noqa: E402
from app.services.infrastructure import readiness  # noqa: E402
from app.services.search_index import get_search_client, schedule_index  # noqa: E402
from app.storage.local import LocalStorage  # noqa: E402
from app.worker import process_search_outbox  # noqa: E402


def main():
    settings = get_settings()
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        raise SystemExit("Refusing: DATABASE_URL must name a disposable *_test database")
    if settings.search_backend != "opensearch" or not settings.opensearch_index.startswith(
        "elor-test-"
    ):
        raise SystemExit(
            "Set SEARCH_BACKEND=opensearch and OPENSEARCH_INDEX=elor-test-<unique-name>"
        )
    root = Path(__file__).resolve().parents[1]
    migration = Config(str(root / "alembic.ini"))
    migration.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(migration, "head")
    queue = "elor-test-" + uuid.uuid4().hex
    actor = Principal(subject="stack-check-author", roles=frozenset({"Contributor"}))
    reviewer = Principal(subject="stack-check-reviewer", roles=frozenset({"Reviewer", "Approver", "Publisher"}))
    process = None
    lo_id = None
    with tempfile.TemporaryDirectory() as directory:
        with open(Path(directory) / "worker.log", "w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "app.worker:celery_app",
                        "worker",
                        "--pool=solo",
                        "--concurrency=1",
                        "--loglevel=WARNING",
                        "--without-gossip",
                        "--without-mingle",
                        "--without-heartbeat",
                        "-Q",
                        queue,
                        "-n",
                        queue + "@%h",
                    ],
                    cwd=root,
                    env=os.environ.copy(),
                    stdout=log,
                    stderr=log,
                )
                with get_session_factory()() as session:
                    assert all(value == "ok" for value in readiness(session).values())
                    title = "quartzstack" + uuid.uuid4().hex
                    lo = content.create_learning_object(
                        session,
                        LocalStorage(Path(directory) / "files"),
                        title=title,
                        filename="check.pdf",
                        content_type="application/pdf",
                        data=b"%PDF-1.4\nStack verification",
                        max_bytes=1024,
                        actor=actor,
                    )
                    lo_id = lo.id
                    workflow.submit(session, lo_id, actor)
                    workflow.decide(session, lo_id, reviewer, "approve")
                    workflow.publish(session, lo_id, reviewer)
                    result = process_search_outbox.apply_async(queue=queue).get(timeout=45)
                    assert result["indexed"] >= 1 and result["failed"] == 0, result
                    hits, total, _ = search.search(
                        session, q=title, subject=None, format=None, page=1, page_size=20
                    )
                    assert total == 1 and hits[0].lo_id == lo_id
                    # SQL must hide a revoked object immediately, before index cleanup.
                    lo.status = "draft"
                    schedule_index(session, lo_id)
                    session.commit()
                    assert (
                        search.search(
                            session, q=title, subject=None, format=None, page=1, page_size=20
                        )[1]
                        == 0
                    )
                    result = process_search_outbox.apply_async(queue=queue).get(timeout=45)
                    assert result["indexed"] >= 1 and result["failed"] == 0, result
                    assert get_search_client().count(index=settings.opensearch_index)["count"] == 0
                print(
                    "PASS: PostgreSQL migrations, Redis broker/results, real Celery execution, "
                    "OpenSearch indexing/search, and publication revocation"
                )
            finally:
                if process is not None:
                    process.terminate()
                    process.wait(timeout=10)
                if lo_id is not None:
                    with get_session_factory()() as session:
                        row = session.scalar(
                            select(LearningObject).where(LearningObject.id == lo_id)
                        )
                        if row:
                            session.delete(row)
                            session.commit()
                get_search_client().indices.delete(index=settings.opensearch_index, ignore=[404])


if __name__ == "__main__":
    main()
