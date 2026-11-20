"""Private S3 storage using the standard AWS task-role credential chain."""

from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.storage.base import StorageBackend


class S3Storage(StorageBackend):
    def __init__(self, bucket: str, *, region: str = "us-east-1", client=None) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET must be configured when STORAGE_BACKEND=s3")
        self._bucket = bucket
        self._client = client if client is not None else boto3.client("s3", region_name=region)

    def save(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ServerSideEncryption="AES256"
        )

    def open(self, key: str) -> BinaryIO:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                raise FileNotFoundError(key) from exc
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
