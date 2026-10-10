"""Bind app connections to administrator-managed webhook destination settings."""

import sqlalchemy as sa
from alembic import op


revision = "e71b682905fd"
down_revision = "d60a571894ec"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_event_destination",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("webhook_id", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.String(), nullable=False),
        sa.Column("trust_revision", sa.String(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_app_event_destination_connection_id", "app_event_destination", ["connection_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_event_destination LIMIT 1")).first():
        raise RuntimeError("Cannot discard app destination bindings")
    op.drop_table("app_event_destination")
