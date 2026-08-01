"""Add company interview profiles and interview profile snapshots.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interview_experience_shares",
        sa.Column("allow_profile_usage", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "company_interview_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("scope", sa.String(length=30), nullable=False, server_default="public"),
        sa.Column("scope_key", sa.String(length=80), nullable=False, server_default="public"),
        sa.Column("company_name", sa.String(length=160), nullable=False),
        sa.Column("normalized_company_name", sa.String(length=160), nullable=False),
        sa.Column("position_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_position_name", sa.String(length=200), nullable=False),
        sa.Column("common_rounds", sa.JSON()),
        sa.Column("frequent_questions", sa.JSON()),
        sa.Column("technical_topics", sa.JSON()),
        sa.Column("difficulty_distribution", sa.JSON()),
        sa.Column("interview_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_experience_ids", sa.JSON()),
        sa.Column("first_observed_at", sa.DateTime()),
        sa.Column("last_observed_at", sa.DateTime()),
        sa.Column("generated_at", sa.DateTime()),
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint(
            "scope_key",
            "normalized_company_name",
            "normalized_position_name",
            name="uq_company_profile_scope_company_position",
        ),
    )
    op.create_index("ix_company_profiles_company", "company_interview_profiles", ["normalized_company_name"])
    op.create_index("ix_company_profiles_position", "company_interview_profiles", ["normalized_position_name"])
    op.create_index("ix_company_profiles_scope", "company_interview_profiles", ["scope_key"])
    op.create_index("ix_company_profiles_interview_count", "company_interview_profiles", ["interview_count"])

    company_profile_column = sa.Column(
        "company_profile_id",
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "company_interview_profiles.id",
            name="fk_interviews_company_profile_id",
            ondelete="SET NULL",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("interviews") as batch_op:
            batch_op.add_column(sa.Column("target_company", sa.String(length=160)))
            batch_op.add_column(sa.Column("target_position", sa.String(length=200)))
            batch_op.add_column(company_profile_column)
            batch_op.add_column(sa.Column("company_profile_snapshot", sa.JSON()))
            batch_op.create_index("ix_interviews_company_profile_id", ["company_profile_id"])
    else:
        op.add_column("interviews", sa.Column("target_company", sa.String(length=160)))
        op.add_column("interviews", sa.Column("target_position", sa.String(length=200)))
        op.add_column("interviews", company_profile_column)
        op.add_column("interviews", sa.Column("company_profile_snapshot", sa.JSON()))
        op.create_index("ix_interviews_company_profile_id", "interviews", ["company_profile_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("interviews") as batch_op:
            batch_op.drop_index("ix_interviews_company_profile_id")
            batch_op.drop_column("company_profile_snapshot")
            batch_op.drop_column("company_profile_id")
            batch_op.drop_column("target_position")
            batch_op.drop_column("target_company")
    else:
        op.drop_index("ix_interviews_company_profile_id", table_name="interviews")
        op.drop_column("interviews", "company_profile_snapshot")
        op.drop_column("interviews", "company_profile_id")
        op.drop_column("interviews", "target_position")
        op.drop_column("interviews", "target_company")

    op.drop_index("ix_company_profiles_interview_count", table_name="company_interview_profiles")
    op.drop_index("ix_company_profiles_scope", table_name="company_interview_profiles")
    op.drop_index("ix_company_profiles_position", table_name="company_interview_profiles")
    op.drop_index("ix_company_profiles_company", table_name="company_interview_profiles")
    op.drop_table("company_interview_profiles")
    op.drop_column("interview_experience_shares", "allow_profile_usage")
