"""Readiness checks have bounded connection timeouts and expose no connection strings."""

from functools import lru_cache

from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.search_index import get_search_client


@lru_cache
def get_redis_client():
    return Redis.from_url(
        get_settings().redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )


def readiness(session: Session) -> dict[str, str]:
    checks = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    if get_settings().search_backend == "opensearch":
        try:
            checks["redis"] = "ok" if get_redis_client().ping() else "unavailable"
        except Exception:
            checks["redis"] = "unavailable"
        try:
            checks["opensearch"] = "ok" if get_search_client().ping() else "unavailable"
        except Exception:
            checks["opensearch"] = "unavailable"
    return checks
