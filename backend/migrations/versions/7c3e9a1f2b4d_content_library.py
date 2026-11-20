"""content_library: rich text, quizzes, templates, archive and soft delete, saved searches

Revision ID: 7c3e9a1f2b4d
Revises: 8931cc425380
Create Date: 2026-11-20 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c3e9a1f2b4d"
down_revision: str | None = "8931cc425380"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("learning_objects") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=16), server_default="file", nullable=False))
        batch.add_column(sa.Column("body", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("is_template", sa.Boolean(), server_default="0", nullable=False))
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("search_text", sa.Text(), server_default="", nullable=False))
        batch.create_index("ix_learning_objects_deleted_at", ["deleted_at"])
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
    )
    op.create_index(
        op.f("ix_saved_searches_owner_subject"), "saved_searches", ["owner_subject"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_saved_searches_owner_subject"), table_name="saved_searches")
    op.drop_table("saved_searches")
    with op.batch_alter_table("learning_objects") as batch:
        batch.drop_index("ix_learning_objects_deleted_at")
        for column in (
            "search_text",
            "deleted_at",
            "archived_at",
            "is_template",
            "revision",
            "body",
            "kind",
        ):
            batch.drop_column(column)
