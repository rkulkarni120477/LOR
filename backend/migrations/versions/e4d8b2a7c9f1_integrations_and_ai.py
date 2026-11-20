"""integrations_and_ai: webhooks, deliveries, branding, AI suggestions

Revision ID: e4d8b2a7c9f1
Revises: 7b3d9e1c4a2f
Create Date: 2026-11-20 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4d8b2a7c9f1"
down_revision: str | None = "7b3d9e1c4a2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhooks")),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(op.f("ix_webhook_deliveries_webhook_id"), "webhook_deliveries", ["webhook_id"])
    op.create_index(op.f("ix_webhook_deliveries_status"), "webhook_deliveries", ["status"])
    op.create_table(
        "branding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_name", sa.String(length=80), nullable=False),
        sa.Column("tagline", sa.String(length=160), nullable=False),
        sa.Column("primary_color", sa.String(length=7), nullable=False),
        sa.Column("logo_url", sa.String(length=1024), nullable=False),
        sa.Column("footer_text", sa.String(length=300), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branding")),
    )
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lo_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("generator", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("edited", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lo_id"], ["learning_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_suggestions")),
    )
    op.create_index(op.f("ix_ai_suggestions_lo_id"), "ai_suggestions", ["lo_id"])
    op.create_index(op.f("ix_ai_suggestions_status"), "ai_suggestions", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_suggestions_status"), table_name="ai_suggestions")
    op.drop_index(op.f("ix_ai_suggestions_lo_id"), table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
    op.drop_table("branding")
    op.drop_index(op.f("ix_webhook_deliveries_status"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_webhook_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhooks")
