"""Learning object creation and retrieval."""

import hashlib
import re
import uuid
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal, Role
from app.db.models import LearningObject, MetadataLOM, Version
from app.services import audit
from app.services.search_index import schedule_index
from app.storage.base import StorageBackend

STATUS_DRAFT = "draft"
PUBLISHED = "published"

# TODO: move to settings once the accepted package types are confirmed with content owners.
ALLOWED_EXTENSIONS = {".zip", ".pdf"}
ALLOWED_CONTENT_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/pdf",
    "application/octet-stream",
}


def _safe_filename(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name or "package"
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:200]


def create_learning_object(
    session: Session,
    storage: StorageBackend,
    *,
    title: str,
    filename: str,
    content_type: str,
    data: bytes,
    max_bytes: int,
    actor: Principal,
) -> LearningObject:
    safe_name = _safe_filename(filename)
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationFailure(f"unsupported package type '{extension}'")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationFailure(f"unsupported content type '{content_type}'")
    if not data:
        raise ValidationFailure("uploaded package is empty")
    if len(data) > max_bytes:
        raise ValidationFailure("uploaded package exceeds the size limit")

    lo_id = str(uuid.uuid4())
    storage_key = f"{lo_id}/v1/{safe_name}"
    storage.save(storage_key, data)  # written before the DB commit; orphan files are acceptable

    lo = LearningObject(id=lo_id, title=title, status=STATUS_DRAFT, created_by=actor.subject)
    lo.versions.append(
        Version(
            version_number=1,
            storage_key=storage_key,
            original_filename=safe_name,
            content_type=content_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            created_by=actor.subject,
        )
    )
    lo.metadata_record = MetadataLOM(
        title=title, keywords=[], lom_json={}, updated_by=actor.subject
    )
    session.add(lo)
    audit.record(
        session,
        actor_subject=actor.subject,
        action="content.create",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"filename": safe_name, "size_bytes": len(data)},
    )
    schedule_index(session, lo_id)
    session.commit()
    return get_learning_object(session, lo_id, actor)


def get_learning_object(session: Session, lo_id: str, actor: Principal) -> LearningObject:
    lo = session.scalar(
        select(LearningObject)
        .where(LearningObject.id == lo_id)
        .options(
            selectinload(LearningObject.versions),
            selectinload(LearningObject.metadata_record),
        )
    )
    if lo is None:
        raise NotFoundError("learning object not found")
    # Learners see only published items; other roles see everything.
    if lo.status != PUBLISHED and not actor.has_any({Role.CONTRIBUTOR.value, Role.REVIEWER.value}):
        raise NotFoundError("learning object not found")
    return lo


def list_learning_objects(
    session: Session,
    actor: Principal,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    subject: str | None = None,
    learning_resource_type: str | None = None,
) -> tuple[list[LearningObject], int]:
    query = select(LearningObject)
    needs_metadata = bool(subject or learning_resource_type)
    if needs_metadata:
        query = query.join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id)
    if subject:
        query = query.where(MetadataLOM.subject == subject)
    if learning_resource_type:
        query = query.where(MetadataLOM.learning_resource_type == learning_resource_type)

    if not actor.has_any({Role.CONTRIBUTOR.value, Role.REVIEWER.value}):
        query = query.where(LearningObject.status == PUBLISHED)
    elif status:
        query = query.where(LearningObject.status == status)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(LearningObject.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
