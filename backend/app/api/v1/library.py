"""Content library: rich text, quizzes, assessments, autosave, templates, archive and delete."""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import LearningObject, SavedSearch
from app.db.session import get_db
from app.schemas.library import (
    AttemptIn,
    BulkIn,
    DraftIn,
    LibraryFilters,
    LibraryItem,
    QuizIn,
    RichTextIn,
    SavedSearchIn,
)
from app.services import library as service
from app.services.access import require_object
from app.storage.base import StorageBackend

router = APIRouter(prefix="/library", tags=["content library"])


@router.get("/templates/catalog")
def template_catalog(actor: Principal = Depends(require_permission("content.read"))):
    from app.services.templates import CATALOG

    return {
        "items": [
            {"key": key, "title": value["title"], "kind": value["kind"]}
            for key, value in CATALOG.items()
        ]
    }


@router.post("/templates/{key}", status_code=201)
def use_builtin_template(
    key: str,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.create")),
):
    from app.services.templates import CATALOG

    if key not in CATALOG:
        raise NotFoundError("Template not found")
    data = {**CATALOG[key], "is_template": False}
    if data.pop("kind") == "rich_text":
        return _item(service.create_rich_text(db, actor, RichTextIn.model_validate(data)))
    return _item(
        service.create_quiz(
            db, actor, QuizIn.model_validate({**data, "kind": CATALOG[key]["kind"]})
        )
    )


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
    filters: LibraryFilters = Depends(),
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
        filters=filters,
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
    if lo.kind in {"quiz", "assessment"} and not service.can_edit_answers(actor, lo, db):
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
        **{
            name: (meta.lom_json or {}).get("lom", {}).get(name) if meta else None
            for name in ("difficulty", "duration_minutes", "learning_standard")
        },
        "language": meta.language if meta else None,
        "license": meta.license if meta else None,
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


@router.put("/{lo_id}/metadata")
def save_file_metadata(
    lo_id: str,
    body: DraftIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
):
    if any(getattr(body, name) is not None for name in ("html", "questions", "passing_score")):
        raise HTTPException(422, "File metadata cannot include authored content")
    lo = service.save_draft(db, actor, lo_id, body, allow_file=True)
    return {"saved": True, "revision": lo.revision}


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


@router.post("/{lo_id}/attempts", status_code=201)
def submit_attempt(
    lo_id: str,
    body: AttemptIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("activity.write")),
):
    import uuid

    from app.core.errors import ConflictError, ValidationFailure
    from app.db.models import AssessmentAttempt
    from app.services import audit

    require_object(db, lo_id, actor, "read")
    lo = db.get(LearningObject, lo_id)
    if lo.kind not in {"quiz", "assessment"} or lo.status != "published":
        raise ConflictError("Only published quizzes and assessments accept attempts")
    questions = (lo.body or {}).get("questions", [])
    if body.revision != lo.revision:
        raise ConflictError("Assessment changed; reload before submitting")
    if (
        not questions
        or len(body.answers) != len(questions)
        or any(
            a < 0 or a >= len(q["options"]) for a, q in zip(body.answers, questions, strict=True)
        )
    ):
        raise ValidationFailure("Answer every question with a valid option")
    points = sum(q["points"] for q in questions)
    score = round(
        100
        * sum(
            q["points"] for a, q in zip(body.answers, questions, strict=True) if a == q["correct"]
        )
        / points,
        2,
    )
    attempt = AssessmentAttempt(
        id=str(uuid.uuid4()),
        lo_id=lo_id,
        actor_subject=actor.subject,
        revision=lo.revision,
        answers=body.answers,
        score=score,
        passed=score >= (lo.body or {}).get("passing_score", 70),
    )
    db.add(attempt)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="assessment.attempt",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"score": score, "passed": attempt.passed},
    )
    db.commit()
    return {"id": attempt.id, "score": score, "passed": attempt.passed}


@router.get("/{lo_id}/attempts")
def attempts(lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    from app.db.models import AssessmentAttempt

    require_object(db, lo_id, actor, "read")
    return {
        "items": [
            {
                "id": row.id,
                "score": row.score,
                "passed": row.passed,
                "revision": row.revision,
                "created_at": row.created_at,
            }
            for row in db.scalars(
                select(AssessmentAttempt)
                .where(
                    AssessmentAttempt.lo_id == lo_id,
                    AssessmentAttempt.actor_subject == actor.subject,
                )
                .order_by(AssessmentAttempt.created_at.desc())
                .limit(100)
            )
        ]
    }


@router.post("/{lo_id}/file")
def replace_file(
    lo_id: str,
    file: UploadFile = File(),
    revision: int = Form(ge=1),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    actor: Principal = Depends(require_permission("content.edit")),
):
    from sqlalchemy import delete

    from app.core.config import get_settings
    from app.core.errors import ConflictError
    from app.db.models import Version
    from app.services import audit, content, versioning

    require_object(db, lo_id, actor, "edit")
    lo = db.get(LearningObject, lo_id)
    if lo.kind != "file" or lo.status not in {"draft", "rejected"} or lo.revision != revision:
        raise ConflictError("Reload the current file draft before replacing it")
    settings = get_settings()
    temporary = content.ingest(
        db,
        storage,
        title=lo.title,
        filename=file.filename or "",
        content_type=file.content_type or "application/octet-stream",
        data=file.file.read(settings.max_upload_bytes + 1),
        max_bytes=settings.max_upload_bytes,
        actor=actor,
        allow_duplicate=True,
        settings=settings,
    )
    if temporary.status == "quarantined":
        raise HTTPException(422, "Replacement was quarantined; the original file was kept")
    db.refresh(lo, with_for_update=True)
    if lo.revision != revision or lo.status not in {"draft", "rejected"}:
        raise ConflictError("The original draft changed during upload; reload and retry")
    source = temporary.versions[-1]
    lo.versions.append(
        Version(
            version_number=max(v.version_number for v in lo.versions) + 1,
            storage_key=source.storage_key,
            original_filename=source.original_filename,
            content_type=source.content_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            created_by=actor.subject,
            scan_status=source.scan_status,
            validation=source.validation,
            package_metadata=source.package_metadata,
            thumbnail_key=source.thumbnail_key,
        )
    )
    lo.revision += 1
    lo.search_text = temporary.search_text
    db.flush()
    db.execute(delete(LearningObject).where(LearningObject.id == temporary.id))
    versioning.ensure_snapshot(db, lo, actor, "file")
    audit.record(
        db,
        actor_subject=actor.subject,
        action="library.file_replace",
        entity_type="learning_object",
        entity_id=lo_id,
    )
    service._commit(db, lo)
    return {"saved": True, "revision": lo.revision}
