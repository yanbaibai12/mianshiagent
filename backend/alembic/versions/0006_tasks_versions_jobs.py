"""Add async tasks, resume versions and job workbench.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "async_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=200), nullable=False, server_default="已排队"),
        sa.Column("resource_type", sa.String(length=80)),
        sa.Column("resource_id", sa.String(length=120)),
        sa.Column("input_payload", sa.JSON()),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("error_type", sa.String(length=120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_async_tasks_user_status", "async_tasks", ["user_id", "status"])
    op.create_index("ix_async_tasks_resource", "async_tasks", ["resource_type", "resource_id"])

    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resume_id", sa.Uuid(), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version_type", sa.String(length=40), nullable=False, server_default="original"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("jd_text", sa.Text()),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("ats_report", sa.JSON()),
        sa.Column("change_details", sa.JSON()),
        sa.Column("source_task_id", sa.Uuid(), sa.ForeignKey("async_tasks.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_resume_versions_resume_number", "resume_versions", ["resume_id", "version_number"])
    op.create_index("ix_resume_versions_user_resume", "resume_versions", ["user_id", "resume_id"])
    op.create_index("ix_resume_versions_type", "resume_versions", ["version_type"])

    op.create_table(
        "job_applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("resume_id", sa.Uuid(), sa.ForeignKey("resumes.id", ondelete="SET NULL")),
        sa.Column("current_resume_version_id", sa.Uuid(), sa.ForeignKey("resume_versions.id", ondelete="SET NULL")),
        sa.Column("company", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("match_score", sa.Numeric(5, 2)),
        sa.Column("ats_report", sa.JSON()),
        sa.Column("interview_id", sa.Uuid(), sa.ForeignKey("interviews.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_job_applications_user_status", "job_applications", ["user_id", "status"])
    op.create_index("ix_job_applications_resume_id", "job_applications", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_job_applications_resume_id", table_name="job_applications")
    op.drop_index("ix_job_applications_user_status", table_name="job_applications")
    op.drop_table("job_applications")
    op.drop_index("ix_resume_versions_type", table_name="resume_versions")
    op.drop_index("ix_resume_versions_user_resume", table_name="resume_versions")
    op.drop_index("ix_resume_versions_resume_number", table_name="resume_versions")
    op.drop_table("resume_versions")
    op.drop_index("ix_async_tasks_resource", table_name="async_tasks")
    op.drop_index("ix_async_tasks_user_status", table_name="async_tasks")
    op.drop_table("async_tasks")
