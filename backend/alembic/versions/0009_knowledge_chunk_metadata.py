"""Add metadata to knowledge chunks.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "metadata" not in _columns("knowledge_chunks"):
        op.add_column("knowledge_chunks", sa.Column("metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "metadata" in _columns("knowledge_chunks"):
        op.drop_column("knowledge_chunks", "metadata")
