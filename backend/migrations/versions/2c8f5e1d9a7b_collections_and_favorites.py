"""collections_and_favorites: nested collections, shares, views, recent access, favorite folders

Revision ID: 2c8f5e1d9a7b
Revises: 4b9e2d7a1c3f
Create Date: 2026-11-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c8f5e1d9a7b"
down_revision: str | None = "4b9e2d7a1c3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("parent_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now())
        )
        batch.create_index("ix_collections_parent_id", ["parent_id"])
        batch.create_foreign_key(
            "fk_collections_parent_id_collections",
            "collections",
            ["parent_id"],
            ["id"],
            ondelete="CASCADE",
        )
    # The old "public" visibility becomes "published", which is the same meaning.
    op.execute("UPDATE collections SET visibility = 'published' WHERE visibility = 'public'")
    op.create_table(
        "collection_shares",
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("grantee_type", sa.String(length=16), nullable=False),
        sa.Column("grantee_id", sa.String(length=255), nullable=False),
        sa.Column("permission", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "grantee_type", "grantee_id"),
    )
    op.create_table(
        "collection_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("viewer_subject", sa.String(length=255), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_views_collection_id", "collection_views", ["collection_id"])
    op.create_index("ix_collection_views_viewer_subject", "collection_views", ["viewer_subject"])
    op.create_index("ix_collection_views_viewed_at", "collection_views", ["viewed_at"])
    op.create_table(
        "recent_access",
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_subject", "kind", "target_id"),
    )
    op.create_index("ix_recent_access_accessed_at", "recent_access", ["accessed_at"])
    op.create_table(
        "favorite_collections",
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_subject", "collection_id"),
    )
    op.create_table(
        "favorite_folders",
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_subject", "name"),
    )


def downgrade() -> None:
    op.drop_table("favorite_folders")
    op.drop_table("favorite_collections")
    op.drop_index("ix_recent_access_accessed_at", table_name="recent_access")
    op.drop_table("recent_access")
    op.drop_index("ix_collection_views_viewed_at", table_name="collection_views")
    op.drop_index("ix_collection_views_viewer_subject", table_name="collection_views")
    op.drop_index("ix_collection_views_collection_id", table_name="collection_views")
    op.drop_table("collection_views")
    op.drop_table("collection_shares")
    op.execute("UPDATE collections SET visibility = 'public' WHERE visibility = 'published'")
    with op.batch_alter_table("collections") as batch:
        batch.drop_constraint("fk_collections_parent_id_collections", type_="foreignkey")
        batch.drop_index("ix_collections_parent_id")
        batch.drop_column("updated_at")
        batch.drop_column("published_at")
        batch.drop_column("parent_id")
