"""Add interview experience shares.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_experience_shares",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("company", sa.String(length=160), nullable=False),
        sa.Column("position", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=80)),
        sa.Column("interview_date", sa.Date()),
        sa.Column("rounds", sa.String(length=200), server_default=""),
        sa.Column("difficulty", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("result", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("tags", sa.JSON()),
        sa.Column("questions", sa.JSON()),
        sa.Column("process", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False, server_default="public"),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="published"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_interview_experience_company", "interview_experience_shares", ["company"])
    op.create_index("ix_interview_experience_position", "interview_experience_shares", ["position"])
    op.create_index("ix_interview_experience_visibility", "interview_experience_shares", ["visibility"])
    op.create_index("ix_interview_experience_created_at", "interview_experience_shares", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_interview_experience_created_at", table_name="interview_experience_shares")
    op.drop_index("ix_interview_experience_visibility", table_name="interview_experience_shares")
    op.drop_index("ix_interview_experience_position", table_name="interview_experience_shares")
    op.drop_index("ix_interview_experience_company", table_name="interview_experience_shares")
    op.drop_table("interview_experience_shares")
