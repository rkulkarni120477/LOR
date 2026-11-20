"""upload_processing: scan status, package validation, multipart upload sessions

Revision ID: 4b9e2d7a1c3f
Revises: 7c3e9a1f2b4d
Create Date: 2026-11-20 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b9e2d7a1c3f"
down_revision: str | None = "7c3e9a1f2b4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("versions") as batch:
        batch.add_column(sa.Column("scan_status", sa.String(length=16), server_default="clean", nullable=False))
        batch.add_column(sa.Column("validation", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("package_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("thumbnail_key", sa.String(length=512), nullable=True))
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("part_size", sa.Integer(), nullable=False),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("backend_upload_id", sa.String(length=512), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("learning_object_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_sessions")),
    )
    op.create_index(op.f("ix_upload_sessions_owner_subject"), "upload_sessions", ["owner_subject"])
    op.create_index(op.f("ix_upload_sessions_status"), "upload_sessions", ["status"])
    op.create_table(
        "upload_parts",
        sa.Column("upload_id", sa.String(length=36), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["upload_sessions.id"],
            name=op.f("fk_upload_parts_upload_id_upload_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("upload_id", "part_number", name=op.f("pk_upload_parts")),
    )


def downgrade() -> None:
    op.drop_table("upload_parts")
    op.drop_index(op.f("ix_upload_sessions_status"), table_name="upload_sessions")
    op.drop_index(op.f("ix_upload_sessions_owner_subject"), table_name="upload_sessions")
    op.drop_table("upload_sessions")
    with op.batch_alter_table("versions") as batch:
        for column in ("thumbnail_key", "package_metadata", "validation", "scan_status"):
            batch.drop_column(column)
