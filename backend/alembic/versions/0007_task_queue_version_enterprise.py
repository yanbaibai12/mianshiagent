"""Harden async task queue metadata.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _foreign_keys(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name) if fk.get("name")}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def _create_fk_if_supported(name: str, source: str, referent: str, local_cols: list[str], remote_cols: list[str]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    if name not in _foreign_keys(source):
        op.create_foreign_key(name, source, referent, local_cols, remote_cols, ondelete="SET NULL")


def upgrade() -> None:
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
    _create_fk_if_supported("fk_resume_versions_parent_version_id", "resume_versions", "resume_versions", ["parent_version_id"], ["id"])
    _create_fk_if_supported("fk_resume_versions_source_job_id", "resume_versions", "job_applications", ["source_job_id"], ["id"])
    _create_index_if_missing("ix_resume_versions_current", "resume_versions", ["resume_id", "is_current"])
    _create_index_if_missing("ix_resume_versions_source_job", "resume_versions", ["source_job_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_versions_source_job", table_name="resume_versions")
    op.drop_index("ix_resume_versions_current", table_name="resume_versions")
    op.drop_column("resume_versions", "notes")
    op.drop_column("resume_versions", "created_by")
    op.drop_column("resume_versions", "status")
    op.drop_column("resume_versions", "is_current")
    op.drop_column("resume_versions", "source_job_id")
    op.drop_column("resume_versions", "parent_version_id")
    op.drop_index("ix_async_tasks_external_job", table_name="async_tasks")
    op.drop_index("ix_async_tasks_queue_backend", table_name="async_tasks")
    op.drop_column("async_tasks", "last_heartbeat_at")
    op.drop_column("async_tasks", "enqueued_at")
    op.drop_column("async_tasks", "cancel_requested")
    op.drop_column("async_tasks", "external_job_id")
    op.drop_column("async_tasks", "queue_name")
    op.drop_column("async_tasks", "queue_backend")
