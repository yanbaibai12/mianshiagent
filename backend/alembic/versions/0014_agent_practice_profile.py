"""Add Agent practice state and training profile.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_question_practice_states",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("question_id", sa.String(length=80), nullable=False),
        sa.Column("mastery_status", sa.String(length=30), nullable=False, server_default="unseen"),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_wrong", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("known_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_review_at", sa.DateTime()),
        sa.Column("last_practiced_at", sa.DateTime()),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "question_id", name="uq_agent_question_practice_user_question"),
    )
    op.create_index("ix_agent_question_practice_user", "agent_question_practice_states", ["user_id"])
    op.create_index("ix_agent_question_practice_question", "agent_question_practice_states", ["question_id"])
    op.create_index("ix_agent_question_practice_next_review", "agent_question_practice_states", ["next_review_at"])

    op.create_table(
        "training_profile_dimensions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("dimension_key", sa.String(length=60), nullable=False),
        sa.Column("dimension_label", sa.String(length=80), nullable=False),
        sa.Column("mastery_score", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("exposure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("known_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weak_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_score_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_signal", sa.String(length=80)),
        sa.Column("last_source", sa.String(length=80)),
        sa.Column("last_practiced_at", sa.DateTime()),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "dimension_key", name="uq_training_profile_user_dimension"),
    )
    op.create_index("ix_training_profile_user", "training_profile_dimensions", ["user_id"])
    op.create_index("ix_training_profile_dimension", "training_profile_dimensions", ["dimension_key"])
    op.create_index("ix_training_profile_mastery", "training_profile_dimensions", ["mastery_score"])


def downgrade() -> None:
    op.drop_index("ix_training_profile_mastery", table_name="training_profile_dimensions")
    op.drop_index("ix_training_profile_dimension", table_name="training_profile_dimensions")
    op.drop_index("ix_training_profile_user", table_name="training_profile_dimensions")
    op.drop_table("training_profile_dimensions")
    op.drop_index("ix_agent_question_practice_next_review", table_name="agent_question_practice_states")
    op.drop_index("ix_agent_question_practice_question", table_name="agent_question_practice_states")
    op.drop_index("ix_agent_question_practice_user", table_name="agent_question_practice_states")
    op.drop_table("agent_question_practice_states")
