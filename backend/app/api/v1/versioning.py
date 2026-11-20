"""Version management endpoints: snapshots, major and minor versions, comparisons, comments,
retention, and full restoration. Rules live in app.services.versioning."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import LearningObject
from app.db.session import get_db
from app.services import versioning as service
from app.services.access import require_object

router = APIRouter(prefix="/versions", tags=["version management"])


class PromoteIn(BaseModel):
    comment: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class RestoreIn(BaseModel):
    seq: int = Field(ge=1)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    snapshot_seq: int | None = Field(default=None, ge=1)


class RetentionIn(BaseModel):
    keep_last: int = Field(ge=5, le=10_000)
    keep_majors: bool = True


def _policy_out(row) -> dict[str, Any]:  # noqa: ANN001
    return {
        "keep_last": row.keep_last,
        "keep_majors": row.keep_majors,
        "updated_by": row.updated_by,
    }


# --- retention (declared first, so /versions/retention is never read as a learning object id) ---


@router.get("/retention")
def get_retention(
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, Any]:
    return _policy_out(service.retention_policy(db))


@router.put("/retention")
def put_retention(
    body: RetentionIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, Any]:
    return _policy_out(service.set_retention(db, actor, body.keep_last, body.keep_majors))


@router.post("/retention/apply")
def apply_retention(
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, int]:
    return service.apply_retention(db, actor)


# --- per item ------------------------------------------------------------------------------------


@router.get("/{lo_id}")
def history(lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    require_object(db, lo_id, actor, "read")
    items = service.history(db, lo_id)
    current = items[-1]["label"] if items else None
    return {"current": current, "items": items}


@router.get("/{lo_id}/snapshots/{seq}")
def snapshot(
    lo_id: str, seq: int, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "read")
    row = service.get(db, lo_id, seq)
    return {**service.summary(row), "content": row.content}


@router.post("/{lo_id}/promote", status_code=201)
def promote(
    lo_id: str,
    body: PromoteIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "edit")
    lo = db.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    return service.summary(service.promote(db, lo, actor, body.comment))


@router.get("/{lo_id}/compare")
def compare(
    lo_id: str,
    a: int = Query(..., ge=1, alias="from"),
    b: int = Query(..., ge=1, alias="to"),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "read")
    return service.compare(service.get(db, lo_id, a), service.get(db, lo_id, b))


@router.post("/{lo_id}/restore")
def restore(
    lo_id: str,
    body: RestoreIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "edit")
    lo = db.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    return service.restore(db, actor, lo, body.seq)


@router.get("/{lo_id}/comments")
def list_comments(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    require_object(db, lo_id, actor, "read")
    return {
        "items": [
            {
                "id": c.id,
                "author": c.author,
                "body": c.body,
                "snapshot_seq": c.snapshot_seq,
                "created_at": c.created_at.isoformat(),
            }
            for c in service.comments(db, lo_id)
        ]
    }


@router.post("/{lo_id}/comments", status_code=201)
def add_comment(
    lo_id: str,
    body: CommentIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "read")
    row = service.add_comment(db, lo_id, actor, body.body.strip(), body.snapshot_seq)
    return {"id": row.id, "author": row.author, "body": row.body, "snapshot_seq": row.snapshot_seq}
