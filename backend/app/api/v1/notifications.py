"""In-app notifications and the email dispatch trigger."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import Notification
from app.db.session import get_db
from app.services import notifications as notify_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "lo_id": row.lo_id,
        "created_at": row.created_at.isoformat(),
        "read": row.read_at is not None,
    }


@router.get("")
def list_notifications(
    unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    query = select(Notification).where(Notification.recipient_subject == actor.subject)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query.order_by(Notification.id.desc()).limit(limit)).all()
    unread_count = db.scalar(
        select(func.count()).where(
            Notification.recipient_subject == actor.subject, Notification.read_at.is_(None)
        )
    )
    return {"items": [_out(r) for r in rows], "unread": unread_count}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    row = db.get(Notification, notification_id)
    if row is None or row.recipient_subject != actor.subject:
        raise NotFoundError("notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        db.commit()
    return _out(row)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    rows = db.scalars(
        select(Notification).where(
            Notification.recipient_subject == actor.subject, Notification.read_at.is_(None)
        )
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        row.read_at = now
    db.commit()
    return {"marked": len(rows)}


@router.post("/dispatch")
def dispatch_email(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, Any]:
    return notify_service.dispatch(db, notify_service.build_sender(settings))
