"""Application settings, read from environment variables and an optional .env file.

Nothing sensitive is hardcoded here. AWS credentials are NOT settings: they come from
the standard boto3 credential chain (env vars, profile, or IAM role).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Runtime environment. "development" enables the dev token issuer and file:// JWKS.
    env: str = "development"
    log_level: str = "INFO"

    # Lightweight default; the full stack uses postgresql+psycopg:// URLs.
    database_url: str = "sqlite:///./lor.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    search_backend: Literal["sql", "opensearch"] = "sql"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "elor-content-v1"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_verify_certs: bool = True
    task_always_eager: bool = False

    cors_origins: list[str] = ["http://localhost:3000"]

    # OIDC / JWT validation.
    oidc_issuer: str = ""
    # https://... for a real IdP. file://<path> is accepted ONLY when env=development.
    oidc_jwks_url: str = ""
    oidc_audience: str = "lor-api"
    oidc_roles_claim: str = "roles"
    oidc_algorithms: list[str] = ["RS256"]
    oidc_jwks_cache_seconds: int = 300

    # AWS / Bedrock. Credentials come from the standard AWS chain, never from settings.
    aws_region: str = "us-east-1"
    bedrock_chat_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024
    guardrails_enabled: bool = False
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = "DRAFT"

    # Storage.
    storage_backend: str = "local"  # "local" | "s3"
    s3_bucket: str = ""
    local_storage_path: str = "./data/storage"
    max_upload_bytes: int = 200 * 1024 * 1024

    # Agent / vector stores (separate SQLite files so Alembic never sees vec0 tables).
    checkpoint_db_path: str = "./checkpoints.db"
    vector_db_path: str = "./vectors.db"

    # Confidence thresholds.
    compliance_threshold: float = 0.7
    metadata_confidence_threshold: float = 0.6
    taxonomy_confidence_threshold: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
