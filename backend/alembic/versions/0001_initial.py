"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "resume_templates",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50)),
        sa.Column("structure", sa.JSON(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "billing_accounts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("original_file", sa.String(length=500)),
        sa.Column("original_text", sa.Text()),
        sa.Column("parsed_data", sa.JSON()),
        sa.Column("optimized_data", sa.JSON()),
        sa.Column("jd_text", sa.Text()),
        sa.Column("match_score", sa.Numeric(5, 2)),
        sa.Column("template_id", sa.String(length=50)),
        sa.Column("is_default", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "interviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", sa.Uuid(), sa.ForeignKey("resumes.id", ondelete="SET NULL")),
        sa.Column("jd_text", sa.Text()),
        sa.Column("status", sa.String(length=20)),
        sa.Column("total_score", sa.Numeric(5, 2)),
        sa.Column("dimension_scores", sa.JSON()),
        sa.Column("summary", sa.Text()),
        sa.Column("weak_points", sa.JSON()),
        sa.Column("suggestions", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("interview_id", sa.Uuid(), sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_point_id", sa.String(length=50)),
        sa.Column("point_title", sa.String(length=200)),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("user_answer", sa.Text()),
        sa.Column("scores", sa.JSON()),
        sa.Column("total_score", sa.Numeric(5, 2)),
        sa.Column("feedback", sa.Text()),
        sa.Column("refined_answer", sa.Text()),
        sa.Column("answered_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature", sa.String(length=50), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False, unique=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=200)),
        sa.Column("tags", sa.JSON()),
        sa.Column("is_builtin", sa.Boolean()),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON()),
        sa.Column("token_estimate", sa.Integer()),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("usage_records")
    op.drop_table("interview_questions")
    op.drop_table("interviews")
    op.drop_table("resumes")
    op.drop_table("billing_accounts")
    op.drop_table("resume_templates")
    op.drop_table("users")
