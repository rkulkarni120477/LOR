"""analytics_reporting: scheduled reports and report runs

Revision ID: 7b3d9e1c4a2f
Revises: a0c6e2f8b5d1
Create Date: 2026-11-20 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3d9e1c4a2f"
down_revision: str | None = "a0c6e2f8b5d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("owner_roles", sa.JSON(), nullable=False),
        sa.Column("owner_group_ids", sa.JSON(), nullable=False),
        sa.Column("owner_department_ids", sa.JSON(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("report", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("cadence", sa.String(length=8), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_reports")),
    )
    op.create_index(op.f("ix_scheduled_reports_owner_subject"), "scheduled_reports", ["owner_subject"])
    op.create_index(op.f("ix_scheduled_reports_next_run_at"), "scheduled_reports", ["next_run_at"])
    op.create_table(
        "report_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("report", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_runs")),
    )
    op.create_index(op.f("ix_report_runs_schedule_id"), "report_runs", ["schedule_id"])
    op.create_index(op.f("ix_report_runs_owner_subject"), "report_runs", ["owner_subject"])


def downgrade() -> None:
    op.drop_index(op.f("ix_report_runs_owner_subject"), table_name="report_runs")
    op.drop_index(op.f("ix_report_runs_schedule_id"), table_name="report_runs")
    op.drop_table("report_runs")
    op.drop_index(op.f("ix_scheduled_reports_next_run_at"), table_name="scheduled_reports")
    op.drop_index(op.f("ix_scheduled_reports_owner_subject"), table_name="scheduled_reports")
    op.drop_table("scheduled_reports")
