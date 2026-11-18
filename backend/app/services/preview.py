"""Read-only package preview for reviewers. Entries are read from the zip in memory; nothing is
extracted to disk. Only zip packages are previewable."""

import mimetypes
import zipfile
from io import BytesIO
from typing import Any

from app.core.errors import NotFoundError, ValidationFailure
from app.storage.base import StorageBackend

MAX_PREVIEW_BYTES = 5 * 1024 * 1024


def _open_zip(storage: StorageBackend, key: str) -> zipfile.ZipFile:
    data = storage.open(key).read()
    try:
        return zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationFailure("preview is available for zip packages only") from exc


def _content_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    if path.lower().endswith(".svg"):
        return "image/svg+xml"
    return guessed or "application/octet-stream"


def list_files(storage: StorageBackend, key: str) -> list[dict[str, Any]]:
    with _open_zip(storage, key) as archive:
        return [
            {
                "path": info.filename,
                "size": info.file_size,
                "content_type": _content_type(info.filename),
            }
            for info in archive.infolist()
            if not info.is_dir()
        ]


def read_file(storage: StorageBackend, key: str, path: str) -> tuple[bytes, str]:
    with _open_zip(storage, key) as archive:
        try:
            info = archive.getinfo(path)
        except KeyError as exc:
            raise NotFoundError("file not found in package") from exc
        if info.is_dir():
            raise NotFoundError("file not found in package")
        if info.file_size > MAX_PREVIEW_BYTES:
            raise ValidationFailure("file is too large to preview")
        return archive.read(path), _content_type(path)
