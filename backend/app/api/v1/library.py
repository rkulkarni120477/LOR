"""Content library: rich text, quizzes, assessments, autosave, templates, archive and delete."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import LearningObject, SavedSearch
from app.db.session import get_db
from app.schemas.library import (
    BulkIn,
    DraftIn,
    LibraryItem,
    QuizIn,
    RichTextIn,
    SavedSearchIn,
)
from app.services import library as service
from app.services.access import require_object

router = APIRouter(prefix="/library", tags=["content library"])


def _item(lo: LearningObject) -> dict[str, Any]:
    return LibraryItem(
        id=lo.id,
        title=lo.title,
        kind=lo.kind,
        status=lo.status,
        is_template=lo.is_template,
        revision=lo.revision,
        created_by=lo.created_by,
        created_at=lo.created_at,
        updated_at=lo.updated_at,
        archived_at=lo.archived_at,
        deleted_at=lo.deleted_at,
    ).model_dump(mode="json")


def _saved(row: SavedSearch) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "params": row.params}


# Saved-search routes come first so they are never captured by /{lo_id}.


@router.get("/saved-searches")
def list_saved_searches(
    db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    return {"items": [_saved(r) for r in service.saved_searches(db, actor)]}


@router.post("/saved-searches", status_code=201)
def create_saved_search(
    body: SavedSearchIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return _saved(service.add_saved_search(db, actor, body.name, body.params))


@router.delete("/saved-searches/{search_id}", status_code=204)
def remove_saved_search(
    search_id: int,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> Response:
    service.delete_saved_search(db, actor, search_id)
    return Response(status_code=204)


@router.get("")
def list_items(
    state: str = Query("active", pattern="^(active|archived|deleted)$"),
    kind: str | None = Query(None, pattern="^(file|rich_text|quiz|assessment)$"),
    template: bool | None = None,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    rows, total = service.list_library(
        db,
        actor,
        state=state,
        kind=kind,
        template=template,
        q=q,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_item(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/rich-text", status_code=201)
def create_rich_text(
    body: RichTextIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    return _item(service.create_rich_text(db, actor, body))


@router.post("/quizzes", status_code=201)
def create_quiz(
    body: QuizIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    return _item(service.create_quiz(db, actor, body))


@router.get("/{lo_id}")
def get_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    lo = db.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    require_object(db, lo_id, actor, "read")
    body = dict(lo.body or {})
    if lo.kind in {"quiz", "assessment"} and not service.can_edit_answers(actor, lo):
        body["questions"] = [
            {k: v for k, v in q.items() if k not in {"correct", "explanation"}}
            for q in body.get("questions", [])
        ]
    meta = lo.metadata_record
    return {
        **_item(lo),
        "description": meta.description if meta else "",
        "subject": meta.subject if meta else None,
        "learning_resource_type": meta.learning_resource_type if meta else None,
        "keywords": meta.keywords if meta else [],
        "body": body,
    }


@router.get("/{lo_id}/preview")
def preview_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return service.preview(db, actor, lo_id)


@router.put("/{lo_id}/draft")
def autosave(
    lo_id: str,
    body: DraftIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    lo = service.save_draft(db, actor, lo_id, body)
    return {"id": lo.id, "revision": lo.revision, "saved_at": lo.updated_at.isoformat()}


@router.post("/{lo_id}/duplicate", status_code=201)
def duplicate_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    return _item(service.duplicate(db, actor, lo_id))


@router.post("/{lo_id}/archive")
def archive_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _item(service.archive(db, actor, lo_id, True))


@router.post("/{lo_id}/unarchive")
def unarchive_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _item(service.archive(db, actor, lo_id, False))


@router.delete("/{lo_id}")
def delete_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _item(service.soft_delete(db, actor, lo_id))


@router.post("/{lo_id}/restore")
def restore_item(
    lo_id: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _item(service.restore(db, actor, lo_id))


@router.post("/bulk")
def bulk_action(
    body: BulkIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    results = service.bulk(db, actor, body.action, body.ids)
    return {"results": results, "succeeded": sum(1 for r in results if r["ok"])}
