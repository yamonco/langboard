"""Explicit card signal scope with indexed occurrence-order evidence projection."""

import sqlalchemy as sa
from alembic import op


revision = "1ba745ac6de6"
down_revision = "0a96349b5cd5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "card_app_signal_binding",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("card_id", sa.BigInteger(), sa.ForeignKey("card.id"), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("app_resource_binding.id"), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("source_change_seq", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("card_id", "resource_id", "external_id", "commit_sha", name="uq_card_app_signal_scope"),
    )
    op.create_index("ix_card_app_signal_binding_card_id", "card_app_signal_binding", ["card_id"])
    op.create_index(
        "ix_app_signal_check_occurrence",
        "app_signal",
        ["resource_id", "event_type", "external_id", "commit_sha", "occurred_at"],
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM card_app_signal_binding LIMIT 1")).first():
        raise RuntimeError("Cannot discard card Signal scope history")
    op.drop_index("ix_app_signal_check_occurrence", table_name="app_signal")
    op.drop_index("ix_card_app_signal_binding_card_id", table_name="card_app_signal_binding")
    op.drop_table("card_app_signal_binding")
