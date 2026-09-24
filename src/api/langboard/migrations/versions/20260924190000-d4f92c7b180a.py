"""Store native execution receipts independently of card descriptions.

Revision ID: d4f92c7b180a
Revises: c7e2b4a091dd
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "d4f92c7b180a"
down_revision: Union[str, Sequence[str], None] = "c7e2b4a091dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_receipt",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(240), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("card_id", "execution_generation", name="uq_execution_receipt_card_generation"),
    )


def downgrade() -> None:
    raise RuntimeError("Execution receipt history must be preserved")
