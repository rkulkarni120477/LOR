"""Optional live test against Amazon Bedrock. Marked `aws`; excluded by default (see pyproject).

Run with:  pytest -m aws
Skips automatically when no AWS credentials are found by the standard boto3 chain.
"""

import boto3
import pytest

from app.core.config import get_settings
from app.llm.bedrock import get_chat_model, get_embeddings


def _has_credentials() -> bool:
    return boto3.Session().get_credentials() is not None


@pytest.mark.aws
@pytest.mark.skipif(not _has_credentials(), reason="no AWS credentials in the environment")
def test_bedrock_chat_and_embeddings_respond():
    settings = get_settings()
    chat = get_chat_model(settings)
    reply = chat.invoke("Reply with the single word: pong")
    assert "pong" in str(reply.content).lower()

    vector = get_embeddings(settings).embed_query("learning object metadata")
    assert len(vector) == settings.embedding_dimensions
