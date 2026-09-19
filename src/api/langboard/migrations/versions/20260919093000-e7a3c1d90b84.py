"""card unread change sequence and read states

Revision ID: e7a3c1d90b84
Revises: c8d2e4f17a90
Create Date: 2026-09-19 09:30:00.000000

"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


# revision identifiers, used by Alembic.
revision: str = "e7a3c1d90b84"
down_revision: Union[str, None] = "c8d2e4f17a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS content_change_seq")

    card_columns = _column_names("card")
    if "last_change_seq" not in card_columns:
        op.add_column("card", sa.Column("last_change_seq", sa.BigInteger(), server_default="0", nullable=False))
    if "last_change_target_type" not in card_columns:
        op.add_column("card", sa.Column("last_change_target_type", sa.String(), server_default="none", nullable=False))
    if "last_change_target_id" not in card_columns:
        op.add_column("card", sa.Column("last_change_target_id", SnowflakeIDType, nullable=True))
    if "last_change_at" not in card_columns:
        op.add_column("card", sa.Column("last_change_at", sa.DateTime(timezone=True), nullable=True))
    if "ix_card_project_id_last_change_seq" not in _index_names("card"):
        op.create_index("ix_card_project_id_last_change_seq", "card", ["project_id", "last_change_seq"])

    pau_columns = _column_names("project_assigned_user")
    if "board_seen_seq" not in pau_columns:
        op.add_column("project_assigned_user", sa.Column("board_seen_seq", sa.BigInteger(), server_default="0", nullable=False))
    if "card_unread_baseline_seq" not in pau_columns:
        op.add_column(
            "project_assigned_user", sa.Column("card_unread_baseline_seq", sa.BigInteger(), server_default="0", nullable=False)
        )

    if "user_card_read_state" not in _table_names():
        op.create_table(
            "user_card_read_state",
            sa.Column("id", SnowflakeIDType, autoincrement=False, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("user_id", SnowflakeIDType, nullable=False),
            sa.Column("card_id", SnowflakeIDType, nullable=False),
            sa.Column("seen_change_seq", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_user_card_read_state_user_id_user"), ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["card_id"], ["card.id"], name=op.f("fk_user_card_read_state_card_id_card"), ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_user_card_read_state")),
            sa.UniqueConstraint("user_id", "card_id", name="uq_user_card_read_state_user_card"),
        )
        op.create_index("ix_user_card_read_state_user_id", "user_card_read_state", ["user_id"], unique=False)
        op.create_index("ix_user_card_read_state_card_id", "user_card_read_state", ["card_id"], unique=False)


def downgrade() -> None:
    if "user_card_read_state" in _table_names():
        op.drop_index("ix_user_card_read_state_card_id", table_name="user_card_read_state")
        op.drop_index("ix_user_card_read_state_user_id", table_name="user_card_read_state")
        op.drop_table("user_card_read_state")
    op.drop_column("project_assigned_user", "card_unread_baseline_seq")
    op.drop_column("project_assigned_user", "board_seen_seq")
    if "ix_card_project_id_last_change_seq" in _index_names("card"):
        op.drop_index("ix_card_project_id_last_change_seq", table_name="card")
    op.drop_column("card", "last_change_at")
    op.drop_column("card", "last_change_target_id")
    op.drop_column("card", "last_change_target_type")
    op.drop_column("card", "last_change_seq")
    op.execute("DROP SEQUENCE IF EXISTS content_change_seq")
