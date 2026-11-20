from io import BytesIO

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage.s3 import S3Storage


def test_private_encrypted_s3_roundtrip_and_missing_object():
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
    )
    storage = S3Storage("private-learning", client=client)
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-learning",
                "Key": "a/v1.pdf",
                "Body": b"file",
                "ServerSideEncryption": "AES256",
            },
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(b"file"), 4)},
            {"Bucket": "private-learning", "Key": "a/v1.pdf"},
        )
        stub.add_response("delete_object", {}, {"Bucket": "private-learning", "Key": "a/v1.pdf"})
        stub.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            http_status_code=404,
            expected_params={"Bucket": "private-learning", "Key": "missing"},
        )
        storage.save("a/v1.pdf", b"file")
        with storage.open("a/v1.pdf") as stream:
            assert stream.read() == b"file"
        storage.delete("a/v1.pdf")
        with pytest.raises(FileNotFoundError):
            storage.open("missing")
        stub.assert_no_pending_responses()


def test_s3_requires_bucket_without_contacting_aws():
    with pytest.raises(ValueError, match="S3_BUCKET"):
        S3Storage("")
