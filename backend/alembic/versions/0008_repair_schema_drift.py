"""Repair schema drift for databases stamped at head.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in _inspector().get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if table_name in _tables() and index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def _add_nullable_org_column(table_name: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        _add_column_if_missing(table_name, sa.Column("organization_id", sa.Uuid()))
    else:
        _add_column_if_missing(
            table_name,
            sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        )


def upgrade() -> None:
    for table_name in ["billing_accounts", "resumes", "interviews", "usage_records", "audit_logs"]:
        _add_nullable_org_column(table_name)

    _add_column_if_missing("interview_questions", sa.Column("module", sa.String(length=40), nullable=False, server_default="resume"))
    _add_column_if_missing("interview_questions", sa.Column("source_section", sa.String(length=200), nullable=True, server_default=""))
    _add_column_if_missing("interview_questions", sa.Column("question_type", sa.String(length=60), nullable=False, server_default="resume_core"))
    _create_index_if_missing("ix_interview_questions_module", "interview_questions", ["module"])
    _create_index_if_missing("ix_interview_questions_question_type", "interview_questions", ["question_type"])

    _add_column_if_missing("async_tasks", sa.Column("queue_backend", sa.String(length=40), nullable=False, server_default="local"))
    _add_column_if_missing("async_tasks", sa.Column("queue_name", sa.String(length=80), nullable=False, server_default="local"))
    _add_column_if_missing("async_tasks", sa.Column("external_job_id", sa.String(length=120)))
    _add_column_if_missing("async_tasks", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("async_tasks", sa.Column("enqueued_at", sa.DateTime()))
    _add_column_if_missing("async_tasks", sa.Column("last_heartbeat_at", sa.DateTime()))
    _create_index_if_missing("ix_async_tasks_queue_backend", "async_tasks", ["queue_backend", "queue_name"])
    _create_index_if_missing("ix_async_tasks_external_job", "async_tasks", ["external_job_id"])

    _add_column_if_missing("resume_versions", sa.Column("parent_version_id", sa.Uuid()))
    _add_column_if_missing("resume_versions", sa.Column("source_job_id", sa.Uuid()))
    _add_column_if_missing("resume_versions", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("resume_versions", sa.Column("status", sa.String(length=30), nullable=False, server_default="active"))
    _add_column_if_missing("resume_versions", sa.Column("created_by", sa.String(length=40), nullable=False, server_default="system"))
    _add_column_if_missing("resume_versions", sa.Column("notes", sa.Text()))
    _create_index_if_missing("ix_resume_versions_current", "resume_versions", ["resume_id", "is_current"])
    _create_index_if_missing("ix_resume_versions_source_job", "resume_versions", ["source_job_id"])


def downgrade() -> None:
    # This migration is a forward-only drift repair. Dropping columns here would
    # risk deleting live data from databases that already had the repaired schema.
    pass
