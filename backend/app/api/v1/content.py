from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import Download, LearningObject, Version, WorkflowState
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.content import ContentDetail, ContentOut, VersionOut
from app.schemas.lom import LOMMetadata
from app.services import audit
from app.services import collections as collection_service
from app.services import content as content_service
from app.services import preview as preview_service
from app.services.access import require_object
from app.services.search_index import schedule_index
from app.services.users import ensure_user
from app.storage.base import StorageBackend

router = APIRouter(prefix="/content", tags=["content"])


def _detail(lo) -> ContentDetail:  # noqa: ANN001
    meta = None
    if lo.metadata_record is not None:
        stored = (lo.metadata_record.lom_json or {}).get("lom") or {
            "title": lo.metadata_record.title
        }
        meta = LOMMetadata.model_validate(stored)
    return ContentDetail(
        id=lo.id,
        title=lo.title,
        status=lo.status,
        created_by=lo.created_by,
        created_at=lo.created_at,
        updated_at=lo.updated_at,
        versions=[VersionOut.model_validate(v) for v in lo.versions],
        metadata=meta,
    )


@router.post("", response_model=ContentDetail, status_code=201)
def upload_content(
    title: Annotated[str, Form(min_length=1, max_length=500)],
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> ContentDetail:
    ensure_user(db, principal)
    data = file.file.read(settings.max_upload_bytes + 1)
    lo = content_service.create_learning_object(
        db,
        storage,
        title=title,
        filename=file.filename or "package",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        max_bytes=settings.max_upload_bytes,
        actor=principal,
        settings=settings,
    )
    return _detail(lo)


@router.get("", response_model=Page[ContentOut])
def list_content(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, max_length=32),
    subject: str | None = Query(None, max_length=255),
    learning_resource_type: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Page[ContentOut]:
    rows, total = content_service.list_learning_objects(
        db,
        principal,
        page=page,
        page_size=page_size,
        status=status,
        subject=subject,
        learning_resource_type=learning_resource_type,
    )
    items = [ContentOut.model_validate(r) for r in rows]
    return Page[ContentOut](items=items, page=page, page_size=page_size, total=total)


@router.get("/{lo_id}/package/files")
def list_package_files(
    lo_id: str,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(require_permission("content.read")),
) -> dict:
    lo = content_service.get_learning_object(db, lo_id, principal)
    if not lo.versions:
        raise NotFoundError("no package for this learning object")
    content_service.assert_servable(lo.versions[-1])
    return {"files": preview_service.list_files(storage, lo.versions[-1].storage_key)}


@router.get("/{lo_id}/package/files/{file_path:path}")
def get_package_file(
    lo_id: str,
    file_path: str,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(require_permission("content.read")),
) -> Response:
    lo = content_service.get_learning_object(db, lo_id, principal)
    if not lo.versions:
        raise NotFoundError("no package for this learning object")
    content_service.assert_servable(lo.versions[-1])
    data, content_type = preview_service.read_file(storage, lo.versions[-1].storage_key, file_path)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # Package content is untrusted: never run its scripts with the app's origin.
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/{lo_id}/thumbnail")
def get_thumbnail(
    lo_id: str,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> Response:
    lo = content_service.get_learning_object(db, lo_id, principal)
    version = lo.versions[-1] if lo.versions else None
    if version is None or not version.thumbnail_key:
        raise NotFoundError("no thumbnail for this learning object")
    content_service.assert_servable(version)
    try:
        with storage.open(version.thumbnail_key) as stream:
            data = stream.read()
    except FileNotFoundError as exc:
        raise NotFoundError("thumbnail file not found") from exc
    media_type = "image/svg+xml" if version.thumbnail_key.endswith(".svg") else "image/png"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/{lo_id}", response_model=ContentDetail)
def get_content(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ContentDetail:
    lo = content_service.get_learning_object(db, lo_id, principal)
    collection_service.touch(db, principal, "object", lo_id)
    db.commit()
    return _detail(lo)


@router.get("/{lo_id}/download")
def download_content(
    lo_id: str,
    version: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> Response:
    require_object(db, lo_id, principal, "download")
    lo = content_service.get_learning_object(db, lo_id, principal)
    # Historical drafts are available only to repository staff.
    if version is not None and not any(
        principal.can(p)
        for p in ("content.edit", "workflow.review", "workflow.approve", "workflow.publish")
    ):
        raise HTTPException(403, "Historical downloads require a repository role")
    selected = (
        next((v for v in lo.versions if v.version_number == version), None)
        if (version is not None)
        else (lo.versions[-1] if lo.versions else None)
    )
    if selected is None:
        raise NotFoundError("version not found")
    content_service.assert_servable(selected)
    try:
        with storage.open(selected.storage_key) as stream:
            data = stream.read()
    except FileNotFoundError as exc:
        raise NotFoundError("content file not found") from exc
    db.add(
        Download(
            lo_id=lo_id, version_number=selected.version_number, actor_subject=principal.subject
        )
    )
    audit.record(
        db,
        actor_subject=principal.subject,
        action="content.download",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"version": selected.version_number},
    )
    db.commit()
    return Response(
        data,
        media_type=selected.content_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(selected.original_filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post(
    "/{lo_id}/versions/{version_number}/restore", response_model=ContentDetail, status_code=201
)
def restore_version(
    lo_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("content.create")),
) -> ContentDetail:
    # Serialize writers on PostgreSQL. The unique version constraint protects SQLite races.
    db.scalar(select(LearningObject).where(LearningObject.id == lo_id).with_for_update())
    lo = content_service.get_learning_object(db, lo_id, principal)
    require_object(db, lo_id, principal, "edit")
    if lo.status in {"submitted", "under_review", "approved"}:
        raise HTTPException(409, "Finish or withdraw the active review before restoring")
    source = next((v for v in lo.versions if v.version_number == version_number), None)
    if source is None:
        raise NotFoundError("version not found")
    new_number = max(v.version_number for v in lo.versions) + 1
    previous_status = lo.status
    lo.versions.append(
        Version(
            version_number=new_number,
            storage_key=source.storage_key,
            original_filename=source.original_filename,
            content_type=source.content_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            created_by=principal.subject,
        )
    )
    lo.status = "draft"
    db.add(
        WorkflowState(
            lo_id=lo_id,
            from_state=previous_status,
            to_state="draft",
            actor_subject=principal.subject,
            comment=f"Restored file version {version_number} as {new_number}",
        )
    )
    audit.record(
        db,
        actor_subject=principal.subject,
        action="version.restore",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"source": version_number, "new_version": new_number},
    )
    try:
        schedule_index(db, lo_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Version changed concurrently; reload and retry") from exc
    return _detail(lo)
