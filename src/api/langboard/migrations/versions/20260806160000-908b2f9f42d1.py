"""add webhook signing secret reference

Revision ID: 908b2f9f42d1
Revises: a4c79b2e1d63
Create Date: 2026-08-06 16:00:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "908b2f9f42d1"
down_revision: Union[str, None] = "a4c79b2e1d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store only the vault identifier for each webhook signing secret."""

    with op.batch_alter_table("webhook_setting", schema=None) as batch_op:
        batch_op.add_column(sa.Column("secret_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove the webhook signing secret reference."""

    with op.batch_alter_table("webhook_setting", schema=None) as batch_op:
        batch_op.drop_column("secret_id")
