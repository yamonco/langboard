"""add card comment text anchors

Revision ID: c7b0d5a6e491
Revises: da39f306364b
Create Date: 2026-09-11 16:00:00
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "c7b0d5a6e491"
down_revision: str | None = "da39f306364b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card_comment") as batch_op:
        batch_op.add_column(sa.Column("anchor", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("card_comment") as batch_op:
        batch_op.drop_column("anchor")
