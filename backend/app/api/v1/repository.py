"""Dashboard summary for the signed-in user. Collections and favorites live in collections.py."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import Principal, get_principal
from app.db.models import Download, LearningObject, Version
from app.db.session import get_db
from app.schemas.content import ContentOut
from app.services.access import read_condition

router = APIRouter(tags=["repository"])


def visible_objects(actor: Principal):
    return select(LearningObject).where(read_condition(actor))


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    scope = visible_objects(actor).subquery()
    counts = dict(db.execute(select(scope.c.status, func.count()).group_by(scope.c.status)).all())
    # Restored versions can reference the same blob; count physical keys once.
    blobs = (
        select(Version.storage_key, func.max(Version.size_bytes).label("size"))
        .where(Version.lo_id.in_(select(scope.c.id)))
        .group_by(Version.storage_key)
        .subquery()
    )
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "storage_bytes": db.scalar(select(func.coalesce(func.sum(blobs.c.size), 0))),
        "downloads": db.scalar(
            select(func.count()).select_from(Download).where(Download.lo_id.in_(select(scope.c.id)))
        ),
        "recent": [
            ContentOut.model_validate(row)
            for row in db.scalars(
                visible_objects(actor).order_by(LearningObject.updated_at.desc()).limit(6)
            )
        ],
    }
