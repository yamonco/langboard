"""Record the immutable original author of each card.

Revision ID: 82cd7e14a3f9
Revises: 7a92d6c13f04
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "82cd7e14a3f9"
down_revision: str | None = "7a92d6c13f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill creators from the earliest durable card-created activity when available."""

    op.add_column("card", sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("card", sa.Column("created_by_bot_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_card_created_by_user_id", "card", ["created_by_user_id"])
    op.create_index("ix_card_created_by_bot_id", "card", ["created_by_bot_id"])
    op.execute(
        sa.text(
            """
            UPDATE card
            SET created_by_user_id = (
                SELECT project_activity.user_id
                FROM project_activity
                WHERE project_activity.card_id = card.id
                  AND project_activity.activity_type = 'card_created'
                ORDER BY project_activity.created_at ASC, project_activity.id ASC
                LIMIT 1
            ),
            created_by_bot_id = (
                SELECT project_activity.bot_id
                FROM project_activity
                WHERE project_activity.card_id = card.id
                  AND project_activity.activity_type = 'card_created'
                ORDER BY project_activity.created_at ASC, project_activity.id ASC
                LIMIT 1
            )
            """
        )
    )


def downgrade() -> None:
    """Remove creator guards only during an explicit rollback."""

    op.drop_index("ix_card_created_by_bot_id", table_name="card")
    op.drop_index("ix_card_created_by_user_id", table_name="card")
    op.drop_column("card", "created_by_bot_id")
    op.drop_column("card", "created_by_user_id")
