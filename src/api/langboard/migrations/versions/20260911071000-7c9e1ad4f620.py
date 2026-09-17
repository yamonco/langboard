"""reconcile external import effect checkpoints

Revision ID: 7c9e1ad4f620
Revises: 54e9c7a1d230
Create Date: 2026-09-11 07:10:00
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "7c9e1ad4f620"
down_revision: str | None = "54e9c7a1d230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CHECKPOINT_COLUMNS = (
    sa.Column("effects_dispatched_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("effects_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    sa.Column("effects_error", sa.Text(), nullable=True),
)


def _column_names() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("external_import_record")}


def upgrade() -> None:
    existing = _column_names()
    for column in CHECKPOINT_COLUMNS:
        if column.name not in existing:
            op.add_column("external_import_record", column)


def downgrade() -> None:
    existing = _column_names()
    for column in reversed(CHECKPOINT_COLUMNS):
        if column.name in existing:
            op.drop_column("external_import_record", column.name)
