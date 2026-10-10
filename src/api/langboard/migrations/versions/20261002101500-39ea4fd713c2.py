"""Retain global source and display snapshots without changing existing local labels."""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision = "39ea4fd713c2"
down_revision = "28d93ec602b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_label", sa.Column("global_label_id", SnowflakeIDType(), nullable=True))
    op.add_column("project_label", sa.Column("global_display", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_project_label_global_source", "project_label", "global_label", ["global_label_id"], ["id"]
    )
    op.create_unique_constraint("uq_project_label_global_source", "project_label", ["project_id", "global_label_id"])


def downgrade() -> None:
    op.drop_constraint("uq_project_label_global_source", "project_label", type_="unique")
    op.drop_constraint("fk_project_label_global_source", "project_label", type_="foreignkey")
    op.drop_column("project_label", "global_display")
    op.drop_column("project_label", "global_label_id")
