"""Completion reports. Only SELECT statements built with SQLAlchemy constructs are used here."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import XapiStatement

COMPLETED_VERB = "http://adlnet.gov/expapi/verbs/completed"


def completion_summary(session: Session) -> dict:
    completed = XapiStatement.verb_id == COMPLETED_VERB
    total = session.scalar(select(func.count()).where(completed)) or 0
    learners = (
        session.scalar(select(func.count(func.distinct(XapiStatement.actor_key))).where(completed))
        or 0
    )
    rows = session.execute(
        select(XapiStatement.object_id, func.count())
        .where(completed)
        .group_by(XapiStatement.object_id)
        .order_by(func.count().desc())
    ).all()
    return {
        "total_completions": int(total),
        "unique_learners": int(learners),
        "by_object": [{"object_id": obj, "completions": int(n)} for obj, n in rows],
    }
