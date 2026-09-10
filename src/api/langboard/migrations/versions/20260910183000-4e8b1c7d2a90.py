"""index archived card pagination

Revision ID: 4e8b1c7d2a90
Revises: b82e65d4f013
Create Date: 2026-09-10 18:30:00.000000

"""

from typing import Sequence, Union
from alembic import op


revision: str = "4e8b1c7d2a90"
down_revision: Union[str, None] = "b82e65d4f013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_card_project_archive_page",
        "card",
        ["project_id", "archived_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_card_project_archive_page", table_name="card")
