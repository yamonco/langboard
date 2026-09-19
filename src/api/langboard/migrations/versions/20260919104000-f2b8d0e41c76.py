"""add card_content_block table

Revision ID: f2b8d0e41c76
Revises: e7a3c1d90b84
Create Date: 2026-09-19 10:40:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


# revision identifiers, used by Alembic.
revision: str = "f2b8d0e41c76"
down_revision: Union[str, None] = "e7a3c1d90b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "card_content_block" in _table_names():
        return
    op.create_table(
        "card_content_block",
        sa.Column("id", SnowflakeIDType, autoincrement=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("card_id", SnowflakeIDType, nullable=False),
        sa.Column("block_type", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], name=op.f("fk_card_content_block_card_id_card"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_content_block")),
    )
    op.create_index("ix_card_content_block_card_id_order", "card_content_block", ["card_id", "order"], unique=False)
    op.create_index("ix_card_content_block_block_type", "card_content_block", ["block_type"], unique=False)


def downgrade() -> None:
    if "card_content_block" not in _table_names():
        return
    op.drop_index("ix_card_content_block_block_type", table_name="card_content_block")
    op.drop_index("ix_card_content_block_card_id_order", table_name="card_content_block")
    op.drop_table("card_content_block")
