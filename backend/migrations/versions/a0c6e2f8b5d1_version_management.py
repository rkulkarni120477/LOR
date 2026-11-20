"""version_management: immutable metadata snapshots, comments, retention, review-to-snapshot link

Revision ID: a0c6e2f8b5d1
Revises: 5f2b8d4e1a9c
Create Date: 2026-11-20 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a0c6e2f8b5d1"
down_revision: str | None = "5f2b8d4e1a9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_cases") as batch:
        batch.add_column(sa.Column("snapshot_id", sa.Integer(), nullable=True))
    op.create_table(
        "metadata_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lo_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("file_version", sa.Integer(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lo_id"], ["learning_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metadata_snapshots")),
        sa.UniqueConstraint("lo_id", "seq", name="uq_snapshot_lo_seq"),
    )
    op.create_index(op.f("ix_metadata_snapshots_lo_id"), "metadata_snapshots", ["lo_id"])
    op.create_table(
        "version_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lo_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_seq", sa.Integer(), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lo_id"], ["learning_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_version_comments")),
    )
    op.create_index(op.f("ix_version_comments_lo_id"), "version_comments", ["lo_id"])
    op.create_table(
        "retention_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keep_last", sa.Integer(), nullable=False),
        sa.Column("keep_majors", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retention_policy")),
    )


def downgrade() -> None:
    op.drop_table("retention_policy")
    op.drop_index(op.f("ix_version_comments_lo_id"), table_name="version_comments")
    op.drop_table("version_comments")
    op.drop_index(op.f("ix_metadata_snapshots_lo_id"), table_name="metadata_snapshots")
    op.drop_table("metadata_snapshots")
    with op.batch_alter_table("review_cases") as batch:
        batch.drop_column("snapshot_id")
