"""Learning object creation and retrieval."""

import hashlib
import re
import uuid
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.errors import DuplicateError, NotFoundError, QuarantinedError, ValidationFailure
from app.core.security import Principal
from app.db.models import LearningObject, MetadataLOM, Version
from app.services import audit, formats, package_validation, versioning
from app.services.access import read_condition
from app.services.malware import build_scanner
from app.services.search_index import schedule_index
from app.services.thumbnails import THUMBNAIL_EXTENSIONS, make_thumbnail
from app.storage.base import StorageBackend

STATUS_DRAFT = "draft"
PUBLISHED = "published"

# TODO: move to settings once the accepted package types are confirmed with content owners.
ALLOWED_EXTENSIONS = set(formats.TYPES)
ALLOWED_CONTENT_TYPES = (
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/pdf",
        "application/octet-stream",
    }
    | set(formats.TYPES.values())
    | {"application/vnd.h5p"}
)


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
    allow_duplicate: bool = False,
    settings: Settings | None = None,
) -> LearningObject:
    """Single entry point for stored packages. Runs the upload pipeline (see ingest)."""
    return ingest(
        session,
        storage,
        title=title,
        filename=filename,
        content_type=content_type,
        data=data,
        max_bytes=max_bytes,
        actor=actor,
        allow_duplicate=allow_duplicate,
        settings=settings,
    )


def check_file_type(filename: str, content_type: str) -> str:
    safe_name = _safe_filename(filename)
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationFailure(f"unsupported package type '{extension}'")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationFailure(f"unsupported content type '{content_type}'")
    return safe_name


def ingest(
    session: Session,
    storage: StorageBackend,
    *,
    title: str,
    filename: str,
    content_type: str,
    data: bytes,
    max_bytes: int,
    actor: Principal,
    allow_duplicate: bool = False,
    settings: Settings | None = None,
) -> LearningObject:
    """Pipeline: type and size checks, malware scan (quarantine on any finding or scanner error),
    package validation (invalid packages are rejected and nothing is stored), duplicate detection
    by SHA-256, then storage with metadata and a thumbnail."""
    safe_name = check_file_type(filename, content_type)
    content_type = formats.TYPES[PurePosixPath(safe_name).suffix.lower()]
    if not data:
        raise ValidationFailure("uploaded package is empty")
    if len(data) > max_bytes:
        raise ValidationFailure("uploaded package exceeds the size limit")
    settings = settings or get_settings()
    lo_id = str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()

    scan = build_scanner(settings).scan(data)
    if not scan.clean:
        # Quarantined bytes are kept for review under a separate prefix and are never served.
        key = f"quarantine/{lo_id}/{safe_name}"
        storage.save(key, data)
        lo = _new_learning_object(session, lo_id, title, actor, "quarantined")
        lo.versions.append(
            _version(
                safe_name,
                key,
                content_type,
                data,
                sha,
                actor,
                "quarantined",
                {"scan": {"status": scan.status, "detail": scan.detail}},
                None,
                None,
            )
        )
        audit.record(
            session,
            actor_subject=actor.subject,
            action="content.quarantine",
            entity_type="learning_object",
            entity_id=lo_id,
            details={"filename": safe_name, "scan": scan.status, "detail": scan.detail},
        )
        schedule_index(session, lo_id)
        session.commit()
        return get_learning_object(session, lo_id, actor)

    report = formats.validate(
        safe_name,
        data,
        package_validation.Limits(
            max_entries=settings.max_package_entries,
            max_uncompressed_bytes=settings.max_uncompressed_bytes,
            max_compression_ratio=settings.max_compression_ratio,
            allow_generic_zip=settings.allow_generic_zip,
        ),
    )
    if not report.valid:
        raise ValidationFailure("package validation failed: " + "; ".join(report.errors[:5]))

    if not allow_duplicate:
        existing = session.scalar(
            select(Version.lo_id)
            .join(LearningObject, LearningObject.id == Version.lo_id)
            .where(
                Version.sha256 == sha,
                Version.scan_status == "clean",
                LearningObject.deleted_at.is_(None),
            )
            .limit(1)
        )
        if existing is not None:
            raise DuplicateError(
                f"this package already exists as {existing}; "
                "resubmit with allow_duplicate=true to store another copy",
                duplicate_of=existing,
            )

    storage_key = f"{lo_id}/v1/{safe_name}"
    storage.save(storage_key, data)  # written before the DB commit; orphan files are acceptable
    thumb, thumb_type = make_thumbnail(data, title, report.standard)
    thumb_key = f"{lo_id}/thumbnail.{THUMBNAIL_EXTENSIONS[thumb_type]}"
    storage.save(thumb_key, thumb)
    package_meta = dict(report.metadata)
    package_meta["size_bytes"] = len(data)
    lo = _new_learning_object(session, lo_id, title, actor, STATUS_DRAFT)
    lo.search_text = (title + " " + formats.extract_text(safe_name, data)).lower()
    lo.versions.append(
        _version(
            safe_name,
            storage_key,
            content_type,
            data,
            sha,
            actor,
            "clean",
            report.to_json(),
            package_meta,
            thumb_key,
        )
    )
    versioning.ensure_snapshot(session, lo, actor, "create")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="content.create",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"filename": safe_name, "size_bytes": len(data), "standard": report.standard},
    )
    schedule_index(session, lo_id)
    session.commit()
    return get_learning_object(session, lo_id, actor)


def _new_learning_object(session, lo_id, title, actor, status) -> LearningObject:
    lo = LearningObject(id=lo_id, title=title, status=status, created_by=actor.subject, revision=1)
    lo.metadata_record = MetadataLOM(
        title=title, keywords=[], lom_json={}, updated_by=actor.subject
    )
    session.add(lo)
    return lo


def _version(
    name, key, content_type, data, sha, actor, scan_status, validation, package_meta, thumb_key
) -> Version:
    return Version(
        version_number=1,
        storage_key=key,
        original_filename=name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha,
        created_by=actor.subject,
        scan_status=scan_status,
        validation=validation,
        package_metadata=package_meta,
        thumbnail_key=thumb_key,
    )


def assert_servable(version: Version) -> None:
    """Every read path that returns package bytes calls this. Quarantine blocks serving."""
    if version.scan_status != "clean":
        raise QuarantinedError("this content is quarantined and cannot be accessed")


def get_learning_object(session: Session, lo_id: str, actor: Principal) -> LearningObject:
    lo = session.scalar(
        select(LearningObject)
        .where(LearningObject.id == lo_id, read_condition(actor))
        .options(
            selectinload(LearningObject.versions),
            selectinload(LearningObject.metadata_record),
        )
    )
    if lo is None:
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
    query = select(LearningObject).where(read_condition(actor))
    needs_metadata = bool(subject or learning_resource_type)
    if needs_metadata:
        query = query.join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id)
    if subject:
        query = query.where(MetadataLOM.subject == subject)
    if learning_resource_type:
        query = query.where(MetadataLOM.learning_resource_type == learning_resource_type)

    if status:
        query = query.where(LearningObject.status == status)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(LearningObject.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
