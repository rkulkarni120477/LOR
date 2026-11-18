"""Read-only, parameterised query templates for the reporting agent.

The agent can only pick a template by name. There is no free-form SQL path. Each template
is a SQLAlchemy Core SELECT; parameters are bound, never interpolated.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import LearningObject, XapiStatement

COMPLETED_VERB = "http://adlnet.gov/expapi/verbs/completed"


def _completions_total(since: datetime | None) -> Select:
    query = select(func.count()).where(XapiStatement.verb_id == COMPLETED_VERB)
    if since is not None:
        query = query.where(XapiStatement.stored_at >= since)
    return query


def _completions_by_object(since: datetime | None) -> Select:
    query = (
        select(XapiStatement.object_id, func.count().label("completions"))
        .where(XapiStatement.verb_id == COMPLETED_VERB)
        .group_by(XapiStatement.object_id)
        .order_by(func.count().desc())
        .limit(20)
    )
    if since is not None:
        query = query.where(XapiStatement.stored_at >= since)
    return query


def _unique_learners(since: datetime | None) -> Select:
    query = select(func.count(func.distinct(XapiStatement.actor_key))).where(
        XapiStatement.verb_id == COMPLETED_VERB
    )
    if since is not None:
        query = query.where(XapiStatement.stored_at >= since)
    return query


def _published_count(_: datetime | None) -> Select:
    return select(func.count()).where(LearningObject.status == "published")


TEMPLATES: dict[str, Callable[[datetime | None], Select]] = {
    "completions_total": _completions_total,
    "completions_by_object": _completions_by_object,
    "unique_learners": _unique_learners,
    "published_count": _published_count,
}


def run_template(
    session: Session, name: str, since: datetime | None = None
) -> list[dict[str, Any]]:
    if name not in TEMPLATES:
        raise KeyError(f"unknown query template: {name}")
    rows = session.execute(TEMPLATES[name](since)).all()
    return [dict(row._mapping) for row in rows]
