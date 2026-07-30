"""Add alert notifications and quality eval candidates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "quality_eval_candidates" not in tables:
        op.create_table(
            "quality_eval_candidates",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("annotation_id", sa.Uuid(), nullable=True),
            sa.Column("target_type", sa.String(length=60), nullable=False),
            sa.Column("target_id", sa.String(length=120), nullable=False),
            sa.Column("source_score", sa.Integer(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("labels", sa.JSON(), nullable=True),
            sa.Column("issue_summary", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["annotation_id"], ["quality_annotations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("annotation_id", name="uq_quality_eval_candidates_annotation"),
        )
        op.create_index("ix_quality_eval_candidates_status", "quality_eval_candidates", ["status", "priority"])
        op.create_index("ix_quality_eval_candidates_target", "quality_eval_candidates", ["target_type", "target_id"])

    if "alert_notifications" not in tables:
        op.create_table(
            "alert_notifications",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("alert_key", sa.String(length=160), nullable=False),
            sa.Column("message_hash", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("feature", sa.String(length=80), nullable=False, server_default="system"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("destination", sa.String(length=200), nullable=False, server_default="webhook"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_type", sa.String(length=120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_alert_notifications_dedupe", "alert_notifications", ["alert_key", "message_hash", "created_at"])
        op.create_index("ix_alert_notifications_status", "alert_notifications", ["status", "severity"])


def downgrade() -> None:
    tables = _tables()
    if "alert_notifications" in tables:
        op.drop_index("ix_alert_notifications_status", table_name="alert_notifications")
        op.drop_index("ix_alert_notifications_dedupe", table_name="alert_notifications")
        op.drop_table("alert_notifications")
    if "quality_eval_candidates" in tables:
        op.drop_index("ix_quality_eval_candidates_target", table_name="quality_eval_candidates")
        op.drop_index("ix_quality_eval_candidates_status", table_name="quality_eval_candidates")
        op.drop_table("quality_eval_candidates")
