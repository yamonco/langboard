"""index project activity recency lookups

Revision ID: a8a74ebed975
Revises: da39f306364b
Create Date: 2026-09-11 02:46:44.795871

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a8a74ebed975"
down_revision: Union[str, None] = "da39f306364b"
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
