"""Resumable multipart uploads. See app/services/uploads.py for the protocol."""

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.security import Principal, require_permission
from app.db.models import UploadSession
from app.db.session import get_db
from app.services import uploads as service
from app.services.users import ensure_user
from app.storage.base import StorageBackend

router = APIRouter(prefix="/uploads", tags=["uploads"])


class CreateUpload(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)
    part_size: int | None = Field(default=None, ge=1)


class AckPart(BaseModel):
    size_bytes: int = Field(gt=0)
    etag: str = Field(min_length=1, max_length=255)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class CompleteUpload(BaseModel):
    allow_duplicate: bool = False


def _result(lo) -> dict[str, Any]:  # noqa: ANN001
    version = lo.versions[-1] if lo.versions else None
    return {
        "id": lo.id,
        "title": lo.title,
        "status": lo.status,
        "scan_status": version.scan_status if version else None,
        "quarantined": bool(version and version.scan_status != "clean"),
        "validation": version.validation if version else None,
        "package_metadata": version.package_metadata if version else None,
        "thumbnail_url": f"/api/v1/content/{lo.id}/thumbnail"
        if version and version.thumbnail_key
        else None,
    }


@router.post("", status_code=201)
def create_upload(
    body: CreateUpload,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    ensure_user(db, principal)
    row = service.create_session(
        db,
        storage,
        settings,
        principal,
        title=body.title,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        part_size=body.part_size,
    )
    return service.describe(db, row)


@router.get("/{upload_id}")
def upload_status(
    upload_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    row = db.get(UploadSession, upload_id)
    if row is None or row.owner_subject != principal.subject:
        raise NotFoundError("upload not found")
    return service.describe(db, row)


@router.get("/{upload_id}/parts/{number}/url")
def part_url(
    upload_id: str,
    number: int,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    return service.part_target(db, storage, settings, principal, upload_id, number)


@router.put("/{upload_id}/parts/{number}")
async def put_part(
    upload_id: str,
    number: int,
    request: Request,
    x_part_sha256: str | None = Header(default=None),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    data = await request.body()
    return service.put_local_part(
        db, storage, settings, principal, upload_id, number, data, x_part_sha256
    )


@router.post("/{upload_id}/parts/{number}/ack")
def ack_part(
    upload_id: str,
    number: int,
    body: AckPart,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    return service.record_direct_part(
        db, settings, principal, upload_id, number, body.size_bytes, body.etag, body.sha256
    )


@router.post("/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    body: CompleteUpload,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    lo = service.complete(
        db, storage, settings, principal, upload_id, allow_duplicate=body.allow_duplicate
    )
    return _result(lo)


@router.post("/{upload_id}/abort")
def abort_upload(
    upload_id: str,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    service.abort(db, storage, settings, principal, upload_id)
    return {"id": upload_id, "status": "aborted"}
