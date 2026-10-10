"""Durable local authenticated Dokploy notification receipts."""

import sqlalchemy as sa
from alembic import op


revision = "6b87540d97c2"
down_revision = "5a76439c86b1"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "dokploy_webhook_binding",
        *_base(),
        sa.Column("board_binding_id", sa.BigInteger(), sa.ForeignKey("board_app_binding.id"), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        sa.Column("credential_reference", sa.String(), nullable=False),
        sa.Column("secret_revision", sa.Integer(), nullable=False),
        sa.Column("connection_revision", sa.String(), nullable=False),
        sa.Column("binding_revision", sa.String(), nullable=False),
        sa.Column("resource_revision", sa.String(), nullable=False),
        sa.Column("notification_id", sa.String(), nullable=True),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.UniqueConstraint("board_binding_id", "connection_id", name="uq_dokploy_webhook_binding"),
        sa.CheckConstraint("state IN ('enabled','disabled')", name=sa.schema.conv("ck_dokploy_webhook_state")),
    )
    op.create_table(
        "dokploy_notification_receipt",
        *_base(),
        sa.Column("config_id", sa.BigInteger(), sa.ForeignKey("dokploy_webhook_binding.id"), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(), nullable=False),
        sa.Column("received_at", sa.String(), nullable=False),
        sa.Column("notification_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.UniqueConstraint("config_id", "config_revision", "payload_digest", name="uq_dokploy_notification_receipt"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM dokploy_notification_receipt LIMIT 1")).first():
        raise RuntimeError("Cannot discard Dokploy notification receipts")
    op.drop_table("dokploy_notification_receipt")
    op.drop_table("dokploy_webhook_binding")
