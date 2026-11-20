"""Content library: rich-text documents, quizzes and assessments, autosave, templates, archival,
soft deletion and restoration, duplication, bulk actions, and format-aware previews."""

import copy
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import LearningObject, MetadataLOM, SavedSearch, Version, utcnow
from app.schemas.library import DraftIn, Question, QuizIn, RichTextIn
from app.services import audit, versioning
from app.services.access import can_read, read_condition, require_object
from app.services.rich_text import plain_text, sanitize_html, search_text
from app.services.search_index import schedule_index
from app.services.users import ensure_user

AUTHORED_KINDS = {"rich_text", "quiz", "assessment"}
METADATA_FIELDS = {"description", "subject", "learning_resource_type", "keywords"}
STATUS_DRAFT = "draft"
MAX_BULK = 100


# --- helpers -----------------------------------------------------------------


def _questions_out(questions: list[Question]) -> list[dict[str, Any]]:
    return [q.model_dump() for q in questions]


def _lom(title, description, subject, resource_type, keywords) -> dict[str, Any]:
    return {
        "lom": {
            "title": title,
            "description": description or None,
            "subject": subject or None,
            "learning_resource_type": resource_type or None,
            "keywords": list(keywords or []),
        }
    }


def _sync_metadata(session: Session, lo: LearningObject, **fields) -> None:
    """Keeps the LOM record in step with the library item, so search and facets see it."""
    record = lo.metadata_record
    if record is None:
        record = MetadataLOM(lo_id=lo.id, title=lo.title, keywords=[], lom_json={})
        lo.metadata_record = record
        session.add(record)
    record.title = lo.title
    record.description = fields.get("description") or None
    record.subject = fields.get("subject") or None
    record.learning_resource_type = fields.get("learning_resource_type") or None
    record.keywords = list(fields.get("keywords") or [])
    record.lom_json = _lom(
        lo.title,
        record.description,
        record.subject,
        record.learning_resource_type,
        record.keywords,
    )
    record.updated_by = fields.get("actor")


def _body_text(lo: LearningObject) -> str:
    body = lo.body or {}
    if lo.kind == "rich_text":
        return plain_text(body.get("html", ""))
    parts = []
    for question in body.get("questions", []):
        parts.append(question.get("prompt", ""))
        parts.extend(question.get("options", []))
    return " ".join(parts)


def _refresh_search(lo: LearningObject) -> None:
    description = lo.metadata_record.description if lo.metadata_record else ""
    lo.search_text = search_text(lo.title, description or "", _body_text(lo))


def _lookup(session: Session, lo_id: str) -> LearningObject:
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    return lo


def _can_manage(actor: Principal, lo: LearningObject) -> bool:
    return actor.is_admin or lo.created_by == actor.subject or actor.can("content.manage")


def can_edit_answers(actor: Principal, lo: LearningObject) -> bool:
    return _can_manage(actor, lo) or actor.can("content.edit")


def _new_authored(
    session: Session,
    actor: Principal,
    *,
    kind: str,
    title: str,
    body: dict[str, Any],
    metadata: dict[str, Any],
    is_template: bool,
) -> LearningObject:
    ensure_user(session, actor)
    lo = LearningObject(
        id=str(uuid.uuid4()),
        title=title,
        status=STATUS_DRAFT,
        created_by=actor.subject,
        kind=kind,
        body=body,
        revision=1,
        is_template=is_template,
    )
    session.add(lo)
    session.flush()
    _sync_metadata(session, lo, **metadata, actor=actor.subject)
    _refresh_search(lo)
    return lo


def _commit(session: Session, lo: LearningObject) -> None:
    lo.updated_at = utcnow()
    schedule_index(session, lo.id)
    session.commit()


# --- creation ----------------------------------------------------------------


def create_rich_text(session: Session, actor: Principal, data: RichTextIn) -> LearningObject:
    lo = _new_authored(
        session,
        actor,
        kind="rich_text",
        title=data.title.strip(),
        body={"html": sanitize_html(data.html)},
        metadata=data.model_dump(include=METADATA_FIELDS),
        is_template=data.is_template,
    )
    versioning.ensure_snapshot(session, lo, actor, "create")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"kind": "rich_text"},
    )
    _commit(session, lo)
    return lo


def create_quiz(session: Session, actor: Principal, data: QuizIn) -> LearningObject:
    lo = _new_authored(
        session,
        actor,
        kind=data.kind,
        title=data.title.strip(),
        body={"passing_score": data.passing_score, "questions": _questions_out(data.questions)},
        metadata=data.model_dump(include=METADATA_FIELDS),
        is_template=data.is_template,
    )
    versioning.ensure_snapshot(session, lo, actor, "create")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.create",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"kind": data.kind},
    )
    _commit(session, lo)
    return lo


# --- autosave ----------------------------------------------------------------


def save_draft(session: Session, actor: Principal, lo_id: str, data: DraftIn) -> LearningObject:
    lo = _lookup(session, lo_id)
    require_object(session, lo_id, actor, "edit")
    if lo.kind not in AUTHORED_KINDS:
        raise ValidationFailure("only rich text, quizzes and assessments can be autosaved")
    if data.revision != lo.revision:
        # Another session saved first. The client must reload rather than overwrite.
        raise ConflictError(f"This item changed elsewhere; current revision is {lo.revision}")
    body = dict(lo.body or {})
    if data.html is not None:
        if lo.kind != "rich_text":
            raise ValidationFailure("html applies to rich text only")
        body["html"] = sanitize_html(data.html)
    if data.questions is not None or data.passing_score is not None:
        if lo.kind == "rich_text":
            raise ValidationFailure("questions apply to quizzes and assessments only")
        if data.questions is not None:
            body["questions"] = _questions_out(data.questions)
        if data.passing_score is not None:
            body["passing_score"] = data.passing_score
    lo.body = body
    if data.title is not None:
        lo.title = data.title.strip()
    record = lo.metadata_record
    current = {
        "description": record.description if record else None,
        "subject": record.subject if record else None,
        "learning_resource_type": record.learning_resource_type if record else None,
        "keywords": record.keywords if record else [],
    }
    for key in ("description", "subject", "learning_resource_type", "keywords"):
        value = getattr(data, key)
        if value is not None:
            current[key] = value
    if data.is_template is not None:
        lo.is_template = data.is_template
    _sync_metadata(session, lo, **current, actor=actor.subject)
    _refresh_search(lo)
    lo.revision += 1
    versioning.ensure_snapshot(session, lo, actor, "metadata")
    _commit(session, lo)
    return lo


# --- duplication, archival, deletion, restoration -----------------------------


def duplicate(session: Session, actor: Principal, lo_id: str) -> LearningObject:
    source = _lookup(session, lo_id)
    if source.deleted_at is not None or not can_read(session, lo_id, actor):
        raise NotFoundError("learning object not found")
    if not actor.can("content.create"):
        raise DomainError("Requires permission: content.create")
    ensure_user(session, actor)
    copy_lo = LearningObject(
        id=str(uuid.uuid4()),
        title=f"Copy of {source.title}"[:500],
        status=STATUS_DRAFT,
        created_by=actor.subject,
        visibility="restricted",
        kind=source.kind,
        body=copy.deepcopy(source.body),
        revision=1,
        is_template=False,
        search_text=source.search_text,
    )
    session.add(copy_lo)
    session.flush()
    for version in source.versions:
        # Storage keys are immutable and never deleted, so the copy can reference the same bytes.
        session.add(
            Version(
                lo_id=copy_lo.id,
                version_number=version.version_number,
                storage_key=version.storage_key,
                original_filename=version.original_filename,
                content_type=version.content_type,
                size_bytes=version.size_bytes,
                sha256=version.sha256,
                created_by=actor.subject,
            )
        )
    if source.metadata_record is not None:
        m = source.metadata_record
        copy_lo.metadata_record = MetadataLOM(
            title=copy_lo.title,
            description=m.description,
            language=m.language,
            subject=m.subject,
            learning_resource_type=m.learning_resource_type,
            keywords=list(m.keywords or []),
            license=m.license,
            rights_description=m.rights_description,
            duration=m.duration,
            lom_json=copy.deepcopy(m.lom_json or {}),
            updated_by=actor.subject,
        )
        if copy_lo.metadata_record.lom_json.get("lom"):
            copy_lo.metadata_record.lom_json["lom"]["title"] = copy_lo.title
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.duplicate",
        entity_type="learning_object",
        entity_id=copy_lo.id,
        details={"source": source.id},
    )
    _commit(session, copy_lo)
    return copy_lo


def archive(session: Session, actor: Principal, lo_id: str, archived: bool) -> LearningObject:
    lo = _lookup(session, lo_id)
    require_object(session, lo_id, actor, "edit")
    if archived and lo.archived_at is None:
        lo.archived_at = utcnow()
    elif not archived:
        lo.archived_at = None
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.archive" if archived else "library.unarchive",
        entity_type="learning_object",
        entity_id=lo_id,
    )
    _commit(session, lo)
    return lo


def soft_delete(session: Session, actor: Principal, lo_id: str) -> LearningObject:
    lo = _lookup(session, lo_id)
    require_object(session, lo_id, actor, "edit")
    lo.deleted_at = utcnow()
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.delete",
        entity_type="learning_object",
        entity_id=lo_id,
    )
    _commit(session, lo)
    return lo


def restore(session: Session, actor: Principal, lo_id: str) -> LearningObject:
    lo = _lookup(session, lo_id)
    if lo.deleted_at is None:
        raise ConflictError("item is not deleted")
    if not _can_manage(actor, lo) or not actor.can("content.edit"):
        raise DomainError("Requires permission: content.edit")
    lo.deleted_at = None
    audit.record(
        session,
        actor_subject=actor.subject,
        action="library.restore",
        entity_type="learning_object",
        entity_id=lo_id,
    )
    _commit(session, lo)
    return lo


def bulk(session: Session, actor: Principal, action: str, ids: list[str]) -> list[dict[str, Any]]:
    if len(ids) > MAX_BULK:
        raise ValidationFailure(f"at most {MAX_BULK} items per bulk action")
    results = []
    for lo_id in dict.fromkeys(ids):  # keep order, drop repeats
        try:
            if action == "archive":
                archive(session, actor, lo_id, True)
            elif action == "unarchive":
                archive(session, actor, lo_id, False)
            elif action == "delete":
                soft_delete(session, actor, lo_id)
            else:
                restore(session, actor, lo_id)
            results.append({"id": lo_id, "ok": True})
        except DomainError as exc:
            session.rollback()
            results.append({"id": lo_id, "ok": False, "message": exc.message})
    return results


# --- previews ----------------------------------------------------------------


def preview(session: Session, actor: Principal, lo_id: str) -> dict[str, Any]:
    lo = _lookup(session, lo_id)
    require_object(session, lo_id, actor, "read")
    base = {"id": lo.id, "title": lo.title, "kind": lo.kind, "revision": lo.revision}
    if lo.kind == "rich_text":
        return {**base, "html": sanitize_html((lo.body or {}).get("html", ""))}
    if lo.kind in {"quiz", "assessment"}:
        show_answers = can_edit_answers(actor, lo)
        questions = []
        for question in (lo.body or {}).get("questions", []):
            item = {
                "prompt": question["prompt"],
                "type": question["type"],
                "options": question["options"],
                "points": question["points"],
            }
            if show_answers:
                item["correct"] = question["correct"]
                item["explanation"] = question.get("explanation", "")
            questions.append(item)
        return {
            **base,
            "passing_score": (lo.body or {}).get("passing_score", 70),
            "total_points": sum(q["points"] for q in questions),
            "questions": questions,
            "answers_visible": show_answers,
        }
    latest = max(lo.versions, key=lambda v: v.version_number, default=None)
    return {
        **base,
        "content_type": latest.content_type if latest else None,
        "original_filename": latest.original_filename if latest else None,
        "size_bytes": latest.size_bytes if latest else None,
        "previewable": latest is not None and latest.content_type == "application/zip",
        "pdf": latest is not None and latest.content_type == "application/pdf",
    }


# --- listing and saved searches ----------------------------------------------


def list_library(
    session: Session,
    actor: Principal,
    *,
    state: str,
    kind: str | None,
    template: bool | None,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[LearningObject], int]:
    if state == "deleted":
        # Deleted items are listed only for their owner, admins, or managers.
        query = select(LearningObject).where(LearningObject.deleted_at.isnot(None))
        if not actor.is_admin and not actor.can("content.manage"):
            query = query.where(LearningObject.created_by == actor.subject)
    else:
        query = select(LearningObject).where(read_condition(actor))
        if state == "archived":
            query = query.where(LearningObject.archived_at.isnot(None))
        else:
            query = query.where(LearningObject.archived_at.is_(None))
    if kind:
        query = query.where(LearningObject.kind == kind)
    if template is not None:
        query = query.where(LearningObject.is_template.is_(template))
    if q:
        for term in q.lower().split()[:10]:
            query = query.where(
                LearningObject.title.ilike(f"%{term}%")
                | LearningObject.search_text.like(f"%{term}%")
            )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(LearningObject.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def saved_searches(session: Session, actor: Principal) -> list[SavedSearch]:
    return list(
        session.scalars(
            select(SavedSearch)
            .where(SavedSearch.owner_subject == actor.subject)
            .order_by(SavedSearch.name)
        )
    )


def add_saved_search(session: Session, actor: Principal, name: str, params: dict) -> SavedSearch:
    row = SavedSearch(owner_subject=actor.subject, name=name.strip(), params=params)
    session.add(row)
    session.commit()
    return row


def delete_saved_search(session: Session, actor: Principal, search_id: int) -> None:
    row = session.get(SavedSearch, search_id)
    if row is None or row.owner_subject != actor.subject:
        raise NotFoundError("saved search not found")
    session.delete(row)
    session.commit()
