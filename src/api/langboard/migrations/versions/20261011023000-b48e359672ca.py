"""Persist explicit card resource selection and permanent decision history."""

import sqlalchemy as sa
from alembic import op


revision = "b48e359672ca"
down_revision = "a37d248561b9"
branch_labels = None
depends_on = None


def upgrade():
    def common():
        return [sa.Column("id", sa.BigInteger(), primary_key=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]

    op.create_table("card_app_resource_selection", *common(),
        sa.Column("card_id", sa.BigInteger(), sa.ForeignKey("card.id"), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        sa.Column("resource_uids", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("card_id", "app_key", name="uq_card_app_resource_selection"))
    op.create_index("ix_card_app_resource_selection_card_id", "card_app_resource_selection", ["card_id"])
    op.create_table("card_app_resource_selection_audit", *common(),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_uids", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False))
    op.create_index("ix_card_app_resource_selection_audit_card_id", "card_app_resource_selection_audit", ["card_id"])


def downgrade():
    for table in ("card_app_resource_selection", "card_app_resource_selection_audit"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard card resource selection history")
    op.drop_table("card_app_resource_selection_audit")
    op.drop_table("card_app_resource_selection")
