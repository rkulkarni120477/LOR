"""S3 storage adapter. STUB: not implemented in this version.

TODO(s3): implement with boto3 `s3` client using settings.s3_bucket and the default AWS
credential chain (IAM role on ECS/App Runner). Needs IAM s3:GetObject, s3:PutObject,
s3:DeleteObject on the bucket. Enable with STORAGE_BACKEND=s3 once implemented.
"""

from typing import BinaryIO

from app.storage.base import StorageBackend


class S3Storage(StorageBackend):
    def __init__(self, bucket: str = "") -> None:
        self._bucket = bucket

    def save(self, key: str, data: bytes) -> None:
        raise NotImplementedError("TODO(s3): S3Storage.save is a stub")

    def open(self, key: str) -> BinaryIO:
        raise NotImplementedError("TODO(s3): S3Storage.open is a stub")

    def delete(self, key: str) -> None:
        raise NotImplementedError("TODO(s3): S3Storage.delete is a stub")
