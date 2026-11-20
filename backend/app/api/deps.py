"""Shared FastAPI dependencies."""

from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage


@lru_cache
def _default_storage() -> StorageBackend:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings.s3_bucket, region=settings.aws_region)
    return LocalStorage(settings.local_storage_path)


def get_storage() -> StorageBackend:
    """Overridable in tests via app.dependency_overrides[get_storage]."""
    return _default_storage()
