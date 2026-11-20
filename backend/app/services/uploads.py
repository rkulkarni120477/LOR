"""Resumable multipart uploads.

Protocol (identical for both storage backends):
  1. create a session with title, filename, content type and total size
  2. for each part, get a target (local: our PUT endpoint; S3: a presigned UploadPart URL)
  3. send the part. Parts are idempotent, so a retry replaces the same part
  4. resume after a pause or crash by reading the session status, which lists completed parts
  5. complete. The parts are assembled, then the upload pipeline (scan, validate, duplicate
     check, store) runs on the assembled bytes

S3 parts go straight from the browser to S3 with presigned URLs. The server records each part's
ETag, then completes the S3 multipart upload. Local parts are stored on the server's storage
backend and assembled there. Temporary objects are removed on completion or abort.
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    StorageUnavailableError,
    ValidationFailure,
)
from app.core.security import Principal
from app.db.models import LearningObject, UploadPart, UploadSession
from app.services import content as content_service
from app.storage.base import StorageBackend

MIN_S3_PART = 5 * 1024 * 1024  # S3 rejects non-final parts smaller than 5 MiB
MAX_PARTS = 10_000  # S3 limit, applied to every backend for consistency
PRESIGN_SECONDS = 3600


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MultipartBackend(Protocol):
    def start(self, session_row: UploadSession) -> str | None: ...
    def part_target(self, session_row: UploadSession, number: int) -> dict[str, Any]: ...
    def assemble(self, session_row: UploadSession, parts: list[UploadPart]) -> None: ...
    def read_assembled(self, session_row: UploadSession) -> bytes: ...
    def discard(self, session_row: UploadSession, parts: list[UploadPart]) -> None: ...


class LocalMultipart:
    """Parts are PUT to this API and stored on the storage backend under _uploads/<id>/."""

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    @staticmethod
    def part_key(upload_id: str, number: int) -> str:
        return f"_uploads/{upload_id}/parts/{number:06d}"

    def start(self, session_row: UploadSession) -> str | None:
        return None

    def part_target(self, session_row: UploadSession, number: int) -> dict[str, Any]:
        return {
            "method": "PUT",
            "url": f"/api/v1/uploads/{session_row.id}/parts/{number}",
            "headers": {"Content-Type": "application/octet-stream"},
            "direct": False,
        }

    def store_part(self, session_row: UploadSession, number: int, data: bytes) -> None:
        self._storage.save(self.part_key(session_row.id, number), data)

    def assemble(self, session_row: UploadSession, parts: list[UploadPart]) -> None:
        chunks = []
        for part in sorted(parts, key=lambda p: p.part_number):
            with self._storage.open(self.part_key(session_row.id, part.part_number)) as stream:
                chunks.append(stream.read())
        self._storage.save(session_row.storage_key, b"".join(chunks))

    def read_assembled(self, session_row: UploadSession) -> bytes:
        with self._storage.open(session_row.storage_key) as stream:
            return stream.read()

    def discard(self, session_row: UploadSession, parts: list[UploadPart]) -> None:
        for part in parts:
            self._storage.delete(self.part_key(session_row.id, part.part_number))
        self._storage.delete(session_row.storage_key)


class S3Multipart:
    """Real S3 multipart uploads. Clients PUT parts to presigned URLs."""

    def __init__(self, storage: StorageBackend, client, bucket: str) -> None:
        self._storage = storage
        self._client = client
        self._bucket = bucket

    def start(self, session_row: UploadSession) -> str:
        response = self._client.create_multipart_upload(
            Bucket=self._bucket,
            Key=session_row.storage_key,
            ServerSideEncryption="AES256",
            ContentType=session_row.content_type,
        )
        return response["UploadId"]

    def part_target(self, session_row: UploadSession, number: int) -> dict[str, Any]:
        url = self._client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self._bucket,
                "Key": session_row.storage_key,
                "UploadId": session_row.backend_upload_id,
                "PartNumber": number,
            },
            ExpiresIn=PRESIGN_SECONDS,
        )
        return {"method": "PUT", "url": url, "headers": {}, "direct": True}

    def assemble(self, session_row: UploadSession, parts: list[UploadPart]) -> None:
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=session_row.storage_key,
            UploadId=session_row.backend_upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": p.part_number, "ETag": p.etag}
                    for p in sorted(parts, key=lambda p: p.part_number)
                ]
            },
        )

    def read_assembled(self, session_row: UploadSession) -> bytes:
        with self._storage.open(session_row.storage_key) as stream:
            return stream.read()

    def discard(self, session_row: UploadSession, parts: list[UploadPart]) -> None:
        if session_row.status == "uploading" and session_row.backend_upload_id:
            self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=session_row.storage_key,
                UploadId=session_row.backend_upload_id,
            )
        else:
            self._storage.delete(session_row.storage_key)


def backend_for(settings: Settings, storage: StorageBackend) -> MultipartBackend:
    if settings.storage_backend == "s3":
        client = getattr(storage, "client", None)
        bucket = getattr(storage, "bucket", "")
        if client is None:
            raise DomainError("S3 storage is not configured")
        return S3Multipart(storage, client, bucket)
    return LocalMultipart(storage)


def _owned(db: Session, upload_id: str, actor: Principal) -> UploadSession:
    row = db.get(UploadSession, upload_id)
    if row is None or row.owner_subject != actor.subject:
        raise NotFoundError("upload not found")
    if row.status in {"uploading", "assembled"}:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if expires <= _utcnow():
            raise DomainError("upload session expired; start a new upload")
    return row


def _parts(db: Session, upload_id: str) -> list[UploadPart]:
    return list(db.scalars(select(UploadPart).where(UploadPart.upload_id == upload_id)))


def _expected_size(row: UploadSession, number: int) -> int:
    if number < row.part_count:
        return row.part_size
    return row.size_bytes - row.part_size * (row.part_count - 1)


def create_session(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    actor: Principal,
    *,
    title: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    part_size: int | None,
) -> UploadSession:
    safe_name = content_service.check_file_type(filename, content_type)
    if size_bytes <= 0:
        raise ValidationFailure("upload size must be positive")
    if size_bytes > settings.max_upload_bytes:
        raise ValidationFailure("uploaded package exceeds the size limit")
    size_limit = MIN_S3_PART if settings.storage_backend == "s3" else 1024 * 1024
    chosen = part_size or settings.upload_part_bytes
    chosen = max(chosen, size_limit)
    count = max(1, math.ceil(size_bytes / chosen))
    if count > MAX_PARTS:
        chosen = math.ceil(size_bytes / MAX_PARTS)
        count = math.ceil(size_bytes / chosen)
    upload_id = str(uuid.uuid4())
    row = UploadSession(
        id=upload_id,
        owner_subject=actor.subject,
        title=title.strip(),
        filename=safe_name,
        content_type=content_type,
        size_bytes=size_bytes,
        part_size=chosen,
        part_count=count,
        status="uploading",
        storage_key=f"_uploads/{upload_id}/object",
        expires_at=_utcnow() + timedelta(seconds=settings.upload_session_seconds),
    )
    row.backend_upload_id = backend_for(settings, storage).start(row)
    db.add(row)
    db.commit()
    return row


def describe(db: Session, row: UploadSession) -> dict[str, Any]:
    done = {p.part_number: p.size_bytes for p in _parts(db, row.id)}
    completed = sorted(done)
    missing = [n for n in range(1, row.part_count + 1) if n not in done]
    return {
        "id": row.id,
        "title": row.title,
        "filename": row.filename,
        "status": row.status,
        "size_bytes": row.size_bytes,
        "part_size": row.part_size,
        "part_count": row.part_count,
        "completed_parts": completed,
        "missing_parts": missing,
        "bytes_received": sum(done.values()),
        "expires_at": row.expires_at.isoformat(),
        "learning_object_id": row.learning_object_id,
    }


def part_target(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    actor: Principal,
    upload_id: str,
    number: int,
) -> dict[str, Any]:
    row = _owned(db, upload_id, actor)
    if row.status != "uploading":
        raise ConflictError(f"upload is {row.status}; parts can no longer be sent")
    if not 1 <= number <= row.part_count:
        raise ValidationFailure("part number is out of range")
    return backend_for(settings, storage).part_target(row, number)


def _record(
    db: Session, row: UploadSession, number: int, size: int, sha256: str | None, etag: str | None
) -> None:
    if row.status != "uploading":
        raise ConflictError(f"upload is {row.status}; parts can no longer be sent")
    if not 1 <= number <= row.part_count:
        raise ValidationFailure("part number is out of range")
    expected = _expected_size(row, number)
    if size != expected:
        raise ValidationFailure(f"part {number} must be {expected} bytes, got {size}")
    part = db.get(UploadPart, (row.id, number))
    if part is None:
        part = UploadPart(upload_id=row.id, part_number=number, size_bytes=size)
        db.add(part)
    part.size_bytes = size
    part.sha256 = sha256 or part.sha256
    part.etag = etag or part.etag
    db.commit()


def put_local_part(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    actor: Principal,
    upload_id: str,
    number: int,
    data: bytes,
    sha256_header: str | None,
) -> dict:
    row = _owned(db, upload_id, actor)
    if not isinstance(backend_for(settings, storage), LocalMultipart):
        raise ConflictError("this upload uses direct storage uploads; PUT to the presigned URL")
    if not 1 <= number <= row.part_count:
        raise ValidationFailure("part number is out of range")
    expected = _expected_size(row, number)
    if len(data) != expected:
        raise ValidationFailure(f"part {number} must be {expected} bytes, got {len(data)}")
    digest = hashlib.sha256(data).hexdigest()
    if sha256_header and sha256_header.lower() != digest:
        raise ValidationFailure("part checksum does not match the data that arrived")
    LocalMultipart(storage).store_part(row, number, data)
    _record(db, row, number, len(data), digest, None)
    return {"part": number, "size_bytes": len(data), "sha256": digest}


def record_direct_part(
    db: Session,
    settings: Settings,
    actor: Principal,
    upload_id: str,
    number: int,
    size: int,
    etag: str,
    sha256: str | None,
) -> dict:
    row = _owned(db, upload_id, actor)
    if not etag:
        raise ValidationFailure("the storage ETag for this part is required")
    _record(db, row, number, size, sha256, etag)
    return {"part": number, "recorded": True}


def complete(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    actor: Principal,
    upload_id: str,
    *,
    allow_duplicate: bool,
) -> LearningObject:
    row = _owned(db, upload_id, actor)
    if row.status == "completed":
        raise ConflictError("upload is already complete")
    if row.status not in {"uploading", "assembled"}:
        raise ConflictError(f"upload is {row.status}")
    parts = _parts(db, upload_id)
    received = {p.part_number for p in parts}
    missing = [n for n in range(1, row.part_count + 1) if n not in received]
    if missing:
        raise ConflictError(f"upload is missing parts: {missing[:20]}")
    backend = backend_for(settings, storage)
    try:
        if row.status == "uploading":
            backend.assemble(row, parts)
            row.status = "assembled"
            db.commit()
        data = backend.read_assembled(row)
    except OSError as exc:
        # The bytes could not be read back (for example, a host security product blocked them).
        # They are never stored, so the upload is rejected rather than served.
        backend.discard(row, parts)
        row.status = "rejected"
        db.commit()
        raise StorageUnavailableError(
            "the uploaded data could not be read from storage for scanning; nothing was stored"
        ) from exc
    if len(data) != row.size_bytes:
        backend.discard(row, parts)
        row.status = "rejected"
        db.commit()
        raise ValidationFailure(f"assembled upload is {len(data)} bytes, expected {row.size_bytes}")
    try:
        lo = content_service.ingest(
            db,
            storage,
            title=row.title,
            filename=row.filename,
            content_type=row.content_type,
            data=data,
            max_bytes=settings.max_upload_bytes,
            actor=actor,
            allow_duplicate=allow_duplicate,
            settings=settings,
        )
    except DomainError as exc:
        if exc.code == "validation_error":
            # Invalid packages are rejected; the temporary object is removed.
            backend.discard(row, parts)
            row.status = "rejected"
            db.commit()
        raise
    backend.discard(row, parts)
    row.status = "completed"
    row.learning_object_id = lo.id
    db.commit()
    return lo


def abort(
    db: Session, storage: StorageBackend, settings: Settings, actor: Principal, upload_id: str
) -> None:
    row = _owned(db, upload_id, actor)
    if row.status in {"completed", "aborted", "rejected"}:
        return
    backend_for(settings, storage).discard(row, _parts(db, upload_id))
    row.status = "aborted"
    db.commit()
