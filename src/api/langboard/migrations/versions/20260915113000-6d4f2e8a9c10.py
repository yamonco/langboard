"""Add independent shared dock positions to project columns.

Revision ID: 6d4f2e8a9c10
Revises: 9c1f4b7e2a60
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "6d4f2e8a9c10"
down_revision: str | None = "9c1f4b7e2a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch_op:
        batch_op.add_column(sa.Column("dock_revision", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.add_column(sa.Column("dock_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.drop_column("dock_order")
    with op.batch_alter_table("project") as batch_op:
        batch_op.drop_column("dock_revision")
