"""Keep execution checklist projections separate from user checklists.

Revision ID: a24ec4b7d19f
Revises: d4f92c7b180a
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "a24ec4b7d19f"
down_revision: Union[str, Sequence[str], None] = "d4f92c7b180a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_checklist_projection",
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("item_uid", sa.String(100), nullable=False),
        sa.Column("evidence_kind", sa.String(100), nullable=False),
        sa.Column("evidence_refs", JSONB(), nullable=False),
        sa.Column("is_checked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("card_id", "execution_generation", "item_uid"),
    )


def downgrade() -> None:
    raise RuntimeError("Execution checklist evidence must be preserved")
