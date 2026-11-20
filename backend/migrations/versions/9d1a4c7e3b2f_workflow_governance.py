"""workflow_governance: approval policies, stages, review cases, tasks, notifications, email outbox

Revision ID: 9d1a4c7e3b2f
Revises: 2c8f5e1d9a7b
Create Date: 2026-11-20 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d1a4c7e3b2f"
down_revision: str | None = "2c8f5e1d9a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_policies")),
        sa.UniqueConstraint("name", name=op.f("uq_approval_policies_name")),
    )
    op.create_table(
        "policy_stages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("approvals_required", sa.Integer(), nullable=False),
        sa.Column("assignees", sa.JSON(), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("escalation_role", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["approval_policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_stages")),
    )
    op.create_index(op.f("ix_policy_stages_policy_id"), "policy_stages", ["policy_id"])
    op.create_table(
        "review_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lo_id", sa.String(length=36), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("policy_name", sa.String(length=120), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("stage_position", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.String(length=255), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lo_id"], ["learning_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_cases")),
    )
    op.create_index(op.f("ix_review_cases_lo_id"), "review_cases", ["lo_id"])
    op.create_index(op.f("ix_review_cases_status"), "review_cases", ["status"])
    op.create_index(op.f("ix_review_cases_submitted_by"), "review_cases", ["submitted_by"])
    op.create_table(
        "stage_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("stage_position", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("assignee_subject", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["review_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_tasks")),
    )
    op.create_index(op.f("ix_stage_tasks_case_id"), "stage_tasks", ["case_id"])
    op.create_index(op.f("ix_stage_tasks_assignee_subject"), "stage_tasks", ["assignee_subject"])
    op.create_index(op.f("ix_stage_tasks_state"), "stage_tasks", ["state"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_subject", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("lo_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_recipient_subject"), "notifications",
                    ["recipient_subject"])
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
    )
    op.create_index(op.f("ix_email_outbox_status"), "email_outbox", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_email_outbox_status"), table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_index(op.f("ix_notifications_recipient_subject"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_stage_tasks_state"), table_name="stage_tasks")
    op.drop_index(op.f("ix_stage_tasks_assignee_subject"), table_name="stage_tasks")
    op.drop_index(op.f("ix_stage_tasks_case_id"), table_name="stage_tasks")
    op.drop_table("stage_tasks")
    op.drop_index(op.f("ix_review_cases_submitted_by"), table_name="review_cases")
    op.drop_index(op.f("ix_review_cases_status"), table_name="review_cases")
    op.drop_index(op.f("ix_review_cases_lo_id"), table_name="review_cases")
    op.drop_table("review_cases")
    op.drop_index(op.f("ix_policy_stages_policy_id"), table_name="policy_stages")
    op.drop_table("policy_stages")
    op.drop_table("approval_policies")
