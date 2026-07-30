"""Add structured module fields to interview questions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interview_questions",
        sa.Column("module", sa.String(length=40), nullable=False, server_default="resume"),
    )
    op.add_column(
        "interview_questions",
        sa.Column("source_section", sa.String(length=200), nullable=True, server_default=""),
    )
    op.add_column(
        "interview_questions",
        sa.Column("question_type", sa.String(length=60), nullable=False, server_default="resume_core"),
    )

    op.execute(
        """
        UPDATE interview_questions
        SET module = CASE
            WHEN resume_point_id LIKE 'project:%' OR point_title LIKE '项目：%' THEN 'project'
            WHEN resume_point_id LIKE 'internship:%' OR point_title LIKE '实习：%' THEN 'internship'
            WHEN resume_point_id LIKE 'agent:%' OR point_title LIKE 'Agent 八股：%' THEN 'agent_fundamentals'
            ELSE 'resume'
        END
        """
    )
    op.execute(
        """
        UPDATE interview_questions
        SET source_section = trim(
            replace(
                replace(
                    replace(
                        replace(coalesce(point_title, ''), '项目：', ''),
                        '实习：',
                        ''
                    ),
                    'Agent 八股：',
                    ''
                ),
                '简历：',
                ''
            )
        )
        """
    )
    op.execute(
        """
        UPDATE interview_questions
        SET question_type = CASE
            WHEN module = 'project' THEN 'project_deep_dive'
            WHEN module = 'internship' THEN 'internship_deep_dive'
            WHEN module = 'agent_fundamentals' THEN 'agent_fundamentals'
            ELSE 'resume_core'
        END
        """
    )

    op.create_index("ix_interview_questions_module", "interview_questions", ["module"])
    op.create_index("ix_interview_questions_question_type", "interview_questions", ["question_type"])


def downgrade() -> None:
    op.drop_index("ix_interview_questions_question_type", table_name="interview_questions")
    op.drop_index("ix_interview_questions_module", table_name="interview_questions")
    op.drop_column("interview_questions", "question_type")
    op.drop_column("interview_questions", "source_section")
    op.drop_column("interview_questions", "module")
