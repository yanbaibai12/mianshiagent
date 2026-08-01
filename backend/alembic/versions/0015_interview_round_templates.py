"""Add interview round template fields.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("interview_template_id", sa.String(length=80), nullable=False, server_default="comprehensive"),
    )
    op.add_column(
        "interviews",
        sa.Column("interview_template_name", sa.String(length=120), nullable=False, server_default="综合面"),
    )
    op.add_column("interviews", sa.Column("template_config_snapshot", sa.JSON()))
    op.create_index("ix_interviews_template_id", "interviews", ["interview_template_id"])


def downgrade() -> None:
    op.drop_index("ix_interviews_template_id", table_name="interviews")
    op.drop_column("interviews", "template_config_snapshot")
    op.drop_column("interviews", "interview_template_name")
    op.drop_column("interviews", "interview_template_id")
