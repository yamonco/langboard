"""index project activity recency lookups

Revision ID: a71d54c3e902
Revises: 3a6f8c1d2e4b
Create Date: 2026-09-10 13:00:00
"""

from typing import Sequence, Union
from alembic import op


revision: str = "a71d54c3e902"
down_revision: Union[str, None] = "3a6f8c1d2e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_project_activity_project_id_created_at",
        "project_activity",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_activity_project_id_created_at", table_name="project_activity")
