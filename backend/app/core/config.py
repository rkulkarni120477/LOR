"""Application settings, read from environment variables and an optional .env file.

Nothing sensitive is hardcoded here. AWS credentials are NOT settings: they come from
the standard boto3 credential chain (env vars, profile, or IAM role).
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


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
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_token_auth_method: Literal["none", "client_secret_basic", "client_secret_post"] = "none"
    oidc_redirect_uri: str = "http://localhost:3000/api/v1/auth/callback"
    app_origin: str = "http://localhost:3000"
    auth_session_seconds: int = 3600
    # Microsoft Entra ID restrictions. SSO fails closed unless both are set.
    # Tenant: the directory (tenant) ID GUID the "tid" claim must match.
    # Domains: email domains allowed to sign in, e.g. ["academian.com"].
    oidc_allowed_tenant_id: str = ""
    oidc_allowed_email_domains: list[str] = []

    @property
    def sso_configured(self) -> bool:
        """True only when Entra SSO is fully configured. Dev-token sign-in is disabled then.

        Entra IDs are GUIDs, so template placeholders such as "<tenant-id>" do not count.
        """
        return bool(
            GUID.fullmatch(self.oidc_client_id)
            and self.oidc_issuer.startswith("https://")
            and GUID.fullmatch(self.oidc_allowed_tenant_id)
            and self.oidc_allowed_email_domains
        )

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

    # Upload processing. Scanner errors quarantine the upload (fail closed).
    # "signature" is built in; "clamav" talks to clamd over TCP (CLAMAV_HOST / CLAMAV_PORT).
    malware_scanner: Literal["signature", "clamav"] = "signature"
    clamav_host: str = ""
    clamav_port: int = 3310
    upload_part_bytes: int = 8 * 1024 * 1024
    upload_session_seconds: int = 24 * 3600
    max_package_entries: int = 10_000
    max_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_compression_ratio: int = 100
    allow_generic_zip: bool = True

    # Email notifications. Left empty, mail stays queued in the outbox until SMTP is configured.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "elor-notifications@localhost"
    smtp_starttls: bool = True
    app_name: str = "ELOR"

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
