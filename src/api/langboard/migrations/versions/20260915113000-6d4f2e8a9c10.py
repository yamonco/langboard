"""Add independent shared dock positions to project columns.

Revision ID: 6d4f2e8a9c10
Revises: 404967cb79df
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "6d4f2e8a9c10"
down_revision: str | None = "404967cb79df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.add_column(sa.Column("dock_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.drop_column("dock_order")
