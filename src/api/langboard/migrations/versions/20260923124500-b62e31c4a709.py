"""Add optional project execution binding.

Revision ID: b62e31c4a709
Revises: d7e8a1c29f04
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision: str = "b62e31c4a709"
down_revision: Union[str, Sequence[str], None] = "d7e8a1c29f04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_execution_binding",
        sa.Column("id", SnowflakeIDType, primary_key=True, autoincrement=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", SnowflakeIDType, sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("column_semantics", sa.JSON(), nullable=False),
        sa.Column("prerequisite_relationship_type_uid", sa.String(), nullable=True),
        sa.Column("webhook_uid", sa.String(), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", name="uq_project_execution_binding_project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_execution_binding")
