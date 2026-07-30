"""Add resume chunks for scoped resume retrieval.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resume_id", sa.Uuid(), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("item_title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON()),
        sa.Column("token_estimate", sa.Integer(), server_default="0"),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("vector_point_id", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_resume_chunks_resume_id", "resume_chunks", ["resume_id"])
    op.create_index("ix_resume_chunks_user_resume", "resume_chunks", ["user_id", "resume_id"])
    op.create_index("ix_resume_chunks_section", "resume_chunks", ["section"])
    op.create_index("ix_resume_chunks_vector_point_id", "resume_chunks", ["vector_point_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_chunks_vector_point_id", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_section", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_user_resume", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_resume_id", table_name="resume_chunks")
    op.drop_table("resume_chunks")
