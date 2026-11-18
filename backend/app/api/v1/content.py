from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.security import Principal, Role, get_principal, require_roles
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.content import ContentDetail, ContentOut, VersionOut
from app.schemas.lom import LOMMetadata
from app.services import content as content_service
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
    principal: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
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


@router.get("/{lo_id}", response_model=ContentDetail)
def get_content(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> ContentDetail:
    lo = content_service.get_learning_object(db, lo_id, principal)
    return _detail(lo)
