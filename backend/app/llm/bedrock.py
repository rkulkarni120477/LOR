"""Bedrock factory. Credentials come only from the standard AWS chain:
environment variables, shared profile (AWS_PROFILE), or an IAM role. Never pass keys here.
"""

from typing import Any

from app.core.config import Settings, get_settings


def get_chat_model(settings: Settings | None = None) -> Any:
    """Claude via LangChain ChatBedrock. Model ID comes from BEDROCK_CHAT_MODEL_ID."""
    from langchain_aws import ChatBedrock

    s = settings or get_settings()
    return ChatBedrock(
        model_id=s.bedrock_chat_model_id,
        region_name=s.aws_region,
        model_kwargs={"temperature": 0.0, "max_tokens": 2048},
    )


def get_embeddings(settings: Settings | None = None) -> Any:
    """Amazon Titan embeddings via LangChain BedrockEmbeddings."""
    from langchain_aws import BedrockEmbeddings

    s = settings or get_settings()
    return BedrockEmbeddings(model_id=s.bedrock_embedding_model_id, region_name=s.aws_region)
