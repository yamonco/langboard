"""Add optional workflow column guidance and reusable template descriptions.

Revision ID: 7a92d6c13f04
Revises: 6f4a9d18c2e1
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op


revision: str = "7a92d6c13f04"
down_revision: str | None = "6f4a9d18c2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve existing columns, template names, ordering, cards, and memberships."""
    op.add_column("project_column", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("project_template", sa.Column("column_descriptions", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    """Remove only new guidance fields; export their values before an intentional downgrade."""
    with op.batch_alter_table("project_template") as batch_op:
        batch_op.drop_column("column_descriptions")
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.drop_column("description")
