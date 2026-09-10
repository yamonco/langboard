"""index card-related activity recency lookups

Revision ID: c3f9a2e7d410
Revises: a8a74ebed975
Create Date: 2026-09-10 19:45:00
"""

from typing import Sequence, Union
from alembic import op


revision: str = "c3f9a2e7d410"
down_revision: Union[str, None] = "a8a74ebed975"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_project_activity_card_id_created_at",
        "project_activity",
        ["card_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_activity_card_id_created_at", table_name="project_activity")
