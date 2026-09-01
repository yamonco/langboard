"""normalize checkitem status storage to EnumLikeType varchar

Revision ID: a4c79b2e1d63
Revises: 09fd3bc91042
Create Date: 2026-08-06 13:25:00

"""

from typing import Sequence, Union
from alembic import op


revision: str = "a4c79b2e1d63"
down_revision: Union[str, None] = "09fd3bc91042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Match legacy PostgreSQL enum columns to the current varchar model."""

    op.execute(
        "ALTER TABLE checkitem ALTER COLUMN status "
        "TYPE VARCHAR USING status::text"
    )
    op.execute(
        "ALTER TABLE checkitem_timer_record ALTER COLUMN status "
        "TYPE VARCHAR USING status::text"
    )
    op.execute("DROP TYPE IF EXISTS checkitemstatus")


def downgrade() -> None:
    """Restore the historical native PostgreSQL enum representation."""

    op.execute(
        "CREATE TYPE checkitemstatus AS ENUM ('Started', 'Paused', 'Stopped')"
    )
    op.execute(
        "ALTER TABLE checkitem ALTER COLUMN status TYPE checkitemstatus "
        "USING (CASE lower(status) "
        "WHEN 'started' THEN 'Started' "
        "WHEN 'paused' THEN 'Paused' "
        "ELSE 'Stopped' END)::checkitemstatus"
    )
    op.execute(
        "ALTER TABLE checkitem_timer_record ALTER COLUMN status "
        "TYPE checkitemstatus USING (CASE lower(status) "
        "WHEN 'started' THEN 'Started' "
        "WHEN 'paused' THEN 'Paused' "
        "ELSE 'Stopped' END)::checkitemstatus"
    )
