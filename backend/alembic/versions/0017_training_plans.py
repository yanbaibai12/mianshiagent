"""Add weekly training plans and tasks.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_interview_id", sa.Uuid(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="SET NULL")),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("plan_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_rate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "organization_id", "week_start", name="uq_training_plan_user_org_week"),
    )
    op.create_index("ix_training_plans_user_week", "training_plans", ["user_id", "week_start"])
    op.create_index("ix_training_plans_org_week", "training_plans", ["organization_id", "week_start"])

    op.create_table(
        "training_plan_tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), sa.ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("related_question_id", sa.String(length=120)),
        sa.Column("related_interview_id", sa.Uuid(as_uuid=True), sa.ForeignKey("interviews.id", ondelete="SET NULL")),
        sa.Column("related_experience_id", sa.Uuid(as_uuid=True), sa.ForeignKey("interview_experience_shares.id", ondelete="SET NULL")),
        sa.Column("related_company_profile_id", sa.Uuid(as_uuid=True), sa.ForeignKey("company_interview_profiles.id", ondelete="SET NULL")),
        sa.Column("target_dimensions", sa.JSON()),
        sa.Column("recommendation_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("dedupe_key", sa.String(length=180), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("plan_id", "dedupe_key", name="uq_training_plan_task_dedupe"),
    )
    op.create_index("ix_training_plan_tasks_plan_date", "training_plan_tasks", ["plan_id", "scheduled_date"])
    op.create_index("ix_training_plan_tasks_status", "training_plan_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_training_plan_tasks_status", table_name="training_plan_tasks")
    op.drop_index("ix_training_plan_tasks_plan_date", table_name="training_plan_tasks")
    op.drop_table("training_plan_tasks")
    op.drop_index("ix_training_plans_org_week", table_name="training_plans")
    op.drop_index("ix_training_plans_user_week", table_name="training_plans")
    op.drop_table("training_plans")
