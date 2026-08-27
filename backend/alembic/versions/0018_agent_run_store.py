"""Add durable Agent Run Store tables.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.String(length=500), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("current_agent_id", sa.String(length=80), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("execution_owner", sa.String(length=120)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint("tokens_used >= 0 AND tool_calls >= 0", name="ck_agent_runs_usage_nonnegative"),
        sa.CheckConstraint("attempts >= 1", name="ck_agent_runs_attempts_positive"),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128 AND length(request_fingerprint) = 64 "
            "AND length(objective) BETWEEN 1 AND 500",
            name="ck_agent_runs_request_lengths",
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_agent_runs_user_idempotency"),
    )
    op.create_index("ix_agent_runs_status_updated", "agent_runs", ["status", "updated_at"])
    op.create_index("ix_agent_runs_lease", "agent_runs", ["execution_owner", "lease_expires_at"])
    op.create_index("ix_agent_runs_user_created", "agent_runs", ["user_id", "created_at"])

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("decision_kind", sa.String(length=30)),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=160)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_run_steps_status",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_run_steps_sequence_positive"),
        sa.CheckConstraint("tokens_used >= 0", name="ck_agent_run_steps_tokens_nonnegative"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_steps_run_sequence"),
    )
    op.create_index("ix_agent_run_steps_run", "agent_run_steps", ["run_id", "sequence"])

    op.create_table(
        "agent_run_trace_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_run_trace_sequence_positive"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_trace_run_sequence"),
    )
    op.create_index("ix_agent_run_trace_run", "agent_run_trace_events", ["run_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_trace_run", table_name="agent_run_trace_events")
    op.drop_table("agent_run_trace_events")
    op.drop_index("ix_agent_run_steps_run", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")
    op.drop_index("ix_agent_runs_user_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_lease", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_updated", table_name="agent_runs")
    op.drop_table("agent_runs")
