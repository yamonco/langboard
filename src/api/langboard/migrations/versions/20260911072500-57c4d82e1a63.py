"""track per-user project view frequency

Revision ID: 57c4d82e1a63
Revises: c3f9a2e7d410
Create Date: 2026-09-11 07:25:00
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "57c4d82e1a63"
down_revision: str | None = "c3f9a2e7d410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("project_assigned_user")}


def upgrade() -> None:
    if "view_count" not in _column_names():
        op.add_column(
            "project_assigned_user",
            sa.Column("view_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        )


def downgrade() -> None:
    if "view_count" in _column_names():
        op.drop_column("project_assigned_user", "view_count")
