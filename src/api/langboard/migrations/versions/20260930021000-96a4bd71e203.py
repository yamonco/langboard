"""Append-only card verification evidence, separate from editable metadata."""

import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision = "96a4bd71e203"
down_revision = "80c532a4e7f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_verification_record",
        sa.Column("id", SnowflakeIDType(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("card_id", SnowflakeIDType(), nullable=False),
        sa.Column("source_change_seq", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("recorded_by_user_id", SnowflakeIDType(), nullable=True),
        sa.Column("recorded_by_bot_id", SnowflakeIDType(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("required_checkitem_uids", sa.JSON(), nullable=False),
        sa.CheckConstraint("decision IN ('verified', 'partial', 'unverified')", name="verification_decision"),
        sa.CheckConstraint("(recorded_by_user_id IS NULL) <> (recorded_by_bot_id IS NULL)", name="verification_actor"),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_verification_record_card_id", "card_verification_record", ["card_id"])


def downgrade() -> None:
    op.drop_index("ix_card_verification_record_card_id", table_name="card_verification_record")
    op.drop_table("card_verification_record")
