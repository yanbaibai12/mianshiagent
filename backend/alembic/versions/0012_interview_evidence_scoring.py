"""Add evidence and scoring details to interviews.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interview_questions", sa.Column("score_details", sa.JSON(), nullable=True))
    op.add_column("interview_questions", sa.Column("evidence", sa.JSON(), nullable=True))
    op.add_column("interview_questions", sa.Column("question_quality", sa.JSON(), nullable=True))
    op.add_column("interviews", sa.Column("report_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("interviews", "report_details")
    op.drop_column("interview_questions", "question_quality")
    op.drop_column("interview_questions", "evidence")
    op.drop_column("interview_questions", "score_details")
