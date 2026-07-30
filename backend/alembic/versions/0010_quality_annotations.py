"""Add quality annotations.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "quality_annotations" in _tables():
        return
    op.create_table(
        "quality_annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("reviewer_role", sa.String(length=40), nullable=False, server_default="user"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_annotations_target", "quality_annotations", ["target_type", "target_id"])
    op.create_index("ix_quality_annotations_user_created", "quality_annotations", ["user_id", "created_at"])


def downgrade() -> None:
    if "quality_annotations" not in _tables():
        return
    op.drop_index("ix_quality_annotations_user_created", table_name="quality_annotations")
    op.drop_index("ix_quality_annotations_target", table_name="quality_annotations")
    op.drop_table("quality_annotations")
