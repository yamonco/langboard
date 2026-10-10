"""Separate app card ownership from card visibility with permanent audit history."""

import sqlalchemy as sa
from alembic import op


revision = "a37d248561b9"
down_revision = "f26c137450a8"
branch_labels = None
depends_on = None


def upgrade():
    def common():
        return [
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        ]

    op.create_table(
        "card_app_ownership",
        *common(),
        sa.Column("card_id", sa.BigInteger(), sa.ForeignKey("card.id"), nullable=False, unique=True),
        sa.Column("app_key", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index("ix_card_app_ownership_card_id", "card_app_ownership", ["card_id"])
    op.create_table(
        "card_app_ownership_audit",
        *common(),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_app_key", sa.String(), nullable=True),
        sa.Column("app_key", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index("ix_card_app_ownership_audit_card_id", "card_app_ownership_audit", ["card_id"])


def downgrade():
    for table in ("card_app_ownership", "card_app_ownership_audit"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard app ownership history")
    op.drop_table("card_app_ownership_audit")
    op.drop_table("card_app_ownership")
