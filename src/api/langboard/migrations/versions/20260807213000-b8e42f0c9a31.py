"""add webhook event allowlist

Revision ID: b8e42f0c9a31
Revises: 7c1f0d6a2e54
Create Date: 2026-08-07 21:30:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "b8e42f0c9a31"
down_revision: Union[str, None] = "7c1f0d6a2e54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a nullable allowlist while preserving all legacy deliveries."""

    if _has_events_column():
        return
    with op.batch_alter_table("webhook_setting", schema=None) as batch_op:
        batch_op.add_column(sa.Column("events", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the allowlist column when it is present."""

    if not _has_events_column():
        return
    with op.batch_alter_table("webhook_setting", schema=None) as batch_op:
        batch_op.drop_column("events")


def _has_events_column() -> bool:
    return any(column["name"] == "events" for column in sa.inspect(op.get_bind()).get_columns("webhook_setting"))
