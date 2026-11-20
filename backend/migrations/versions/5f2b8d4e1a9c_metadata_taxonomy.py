"""metadata_taxonomy: vocabularies, term status and merging, custom metadata fields

Revision ID: 5f2b8d4e1a9c
Revises: 9d1a4c7e3b2f
Create Date: 2026-11-20 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f2b8d4e1a9c"
down_revision: str | None = "9d1a4c7e3b2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("taxonomy_terms") as batch:
        batch.add_column(sa.Column("status", sa.String(length=16), server_default="active", nullable=False))
        batch.add_column(sa.Column("merged_into_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_taxonomy_terms_merged_into_id_taxonomy_terms",
            "taxonomy_terms",
            ["merged_into_id"],
            ["id"],
        )
    op.create_table(
        "vocabularies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("locked", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vocabularies")),
        sa.UniqueConstraint("name", name=op.f("uq_vocabularies_name")),
    )
    op.create_table(
        "metadata_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("vocabulary", sa.String(length=64), nullable=True),
        sa.Column("required", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("help_text", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metadata_fields")),
        sa.UniqueConstraint("key", name=op.f("uq_metadata_fields_key")),
    )


def downgrade() -> None:
    op.drop_table("metadata_fields")
    op.drop_table("vocabularies")
    with op.batch_alter_table("taxonomy_terms") as batch:
        batch.drop_constraint("fk_taxonomy_terms_merged_into_id_taxonomy_terms", type_="foreignkey")
        batch.drop_column("merged_into_id")
        batch.drop_column("status")
