"""enforce one active system checklist per card

Revision ID: a91c4d2e7f10
Revises: c4e7a92b1d63
Create Date: 2026-09-20 05:30:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "a91c4d2e7f10"
down_revision: Union[str, None] = "c4e7a92b1d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve the oldest active row if a pre-constraint race already created duplicates.
    op.execute(
        sa.text(
            """
            UPDATE checklist
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY id) AS row_number
                    FROM checklist
                    WHERE is_system = true AND deleted_at IS NULL
                ) AS ranked
                WHERE row_number > 1
            )
            """
        )
    )
    op.create_index(
        "uq_checklist_active_system_card",
        "checklist",
        ["card_id"],
        unique=True,
        postgresql_where=sa.text("is_system AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_system = 1 AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_checklist_active_system_card", table_name="checklist")
