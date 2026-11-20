"""Collections, favorites and download events.

Revision ID: a12b34c56d78
Revises: 851cd3b1621c
"""

import sqlalchemy as sa
from alembic import op

revision = "a12b34c56d78"
down_revision = "851cd3b1621c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_subject", sa.String(255), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_collections_owner_subject", "collections", ["owner_subject"])
    op.create_table(
        "collection_items",
        sa.Column(
            "collection_id",
            sa.String(36),
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "lo_id",
            sa.String(36),
            sa.ForeignKey("learning_objects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "favorites",
        sa.Column("owner_subject", sa.String(255), primary_key=True),
        sa.Column(
            "lo_id",
            sa.String(36),
            sa.ForeignKey("learning_objects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("folder", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lo_id",
            sa.String(36),
            sa.ForeignKey("learning_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_downloads_lo_id", "downloads", ["lo_id"])
    op.create_index("ix_downloads_actor_subject", "downloads", ["actor_subject"])


def downgrade():
    for table in ("downloads", "favorites", "collection_items", "collections"):
        op.drop_table(table)
