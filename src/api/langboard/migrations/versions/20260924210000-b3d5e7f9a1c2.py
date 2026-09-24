"""Converge execution delivery into the outbox task with terminal states.

Revision ID: b3d5e7f9a1c2
Revises: a24ec4b7d19f
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "b3d5e7f9a1c2"
down_revision: Union[str, Sequence[str], None] = "a24ec4b7d19f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_outbox",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("execution_outbox", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    # Rows stranded in 'scheduled' by the previous two-stage pipeline can never
    # reach a terminal state: no callback marked them delivered or failed after
    # the separate delivery task finished. Queue them again; consumers already
    # deduplicate logical deliveries by event id and generation.
    op.execute("UPDATE execution_outbox SET state = 'pending' WHERE state = 'scheduled'")


def downgrade() -> None:
    raise RuntimeError("Execution delivery history must be preserved")
