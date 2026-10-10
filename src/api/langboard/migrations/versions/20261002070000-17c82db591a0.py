"""Add reusable global label definitions without changing project labels."""
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision = "17c82db591a0"
down_revision = "96a4bd71e203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_label",
        sa.Column("id", SnowflakeIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("translations", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("global_label")
