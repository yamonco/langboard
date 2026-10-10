"""Store explicit workflow meaning on columns without changing existing cards.

Revision ID: 80c532a4e7f1
Revises: 2c4e8a1f6b30
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "80c532a4e7f1"
down_revision: Union[str, None] = "2c4e8a1f6b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.add_column(sa.Column("workflow_stage", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "ck_project_column_workflow_stage",
            "workflow_stage IS NULL OR workflow_stage IN ('backlog', 'ready', 'active', 'review', 'closed', 'reference')",
        )


def downgrade() -> None:
    with op.batch_alter_table("project_column") as batch_op:
        batch_op.drop_constraint("ck_project_column_workflow_stage", type_="check")
        batch_op.drop_column("workflow_stage")
