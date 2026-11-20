"""celery -A app.worker:celery_app worker; run one separate beat scheduler."""

import logging
from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import SearchIndexJob
from app.db.session import get_session_factory
from app.services.search_index import ensure_index, index_object

settings = get_settings()
celery_app = Celery("elor", broker=settings.redis_url, backend=settings.celery_result_backend)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.task_always_eager,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_soft_time_limit=90,
    task_time_limit=120,
    beat_schedule={"search-outbox": {"task": "elor.process_search_outbox", "schedule": 10.0}},
)
logger = logging.getLogger(__name__)


@celery_app.task(name="elor.process_search_outbox")
def process_search_outbox(batch_size: int = 100) -> dict[str, int]:
    if get_settings().search_backend != "opensearch":
        return {"indexed": 0, "failed": 0}
    ensure_index()
    indexed = failed = 0
    with get_session_factory()() as session:
        # Each row lock is held through projection + deletion. Skip locked permits workers
        # to cooperate; replay after a worker crash is safe because indexing is idempotent.
        for _ in range(min(max(batch_size, 1), 1000)):
            job = session.scalar(
                select(SearchIndexJob)
                .where(SearchIndexJob.available_at <= datetime.now(UTC))
                .order_by(SearchIndexJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                break
            try:
                index_object(session, job.lo_id)
            except Exception:
                logger.exception("search projection failed", extra={"lo_id": job.lo_id})
                job.attempts += 1
                job.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(2 ** min(job.attempts, 10), 900)
                )
                failed += 1
            else:
                session.delete(job)
                indexed += 1
            session.commit()
    return {"indexed": indexed, "failed": failed}
