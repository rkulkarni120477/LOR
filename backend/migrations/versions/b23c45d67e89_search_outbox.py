"""Transactional search indexing outbox.

Revision ID: b23c45d67e89
Revises: a12b34c56d78
"""

import sqlalchemy as sa
from alembic import op

revision = "b23c45d67e89"
down_revision = "a12b34c56d78"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_index_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lo_id", sa.String(36), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_index_jobs_lo_id", "search_index_jobs", ["lo_id"])
    op.create_index("ix_search_index_jobs_available_at", "search_index_jobs", ["available_at"])


def downgrade():
    op.drop_table("search_index_jobs")
