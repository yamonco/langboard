"""add typed linked resources to cards

Revision ID: 3a6f8c1d2e4b
Revises: 82cd7e14a3f9
Create Date: 2026-09-10 10:30:00
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "3a6f8c1d2e4b"
down_revision: Union[str, None] = "82cd7e14a3f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store source identity without copying source content into cards."""

    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_uid", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_card_`linked_source_complete`"),
            "(source_type IS NULL) = (source_uid IS NULL)",
        )
        batch_op.create_unique_constraint(
            "uq_card_linked_resource",
            ["project_id", "source_type", "source_uid"],
        )


def downgrade() -> None:
    """Remove linked-resource identity while preserving ordinary cards."""

    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_constraint("uq_card_linked_resource", type_="unique")
        batch_op.drop_constraint(op.f("ck_card_`linked_source_complete`"), type_="check")
        batch_op.drop_column("source_uid")
        batch_op.drop_column("source_type")
