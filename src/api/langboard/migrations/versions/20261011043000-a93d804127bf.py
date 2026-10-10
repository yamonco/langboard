"""Preserve native app reception acknowledgments independently of runtime state."""

import sqlalchemy as sa
from alembic import op


revision = "a93d804127bf"
down_revision = "f82c793016ae"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_execution_acknowledgment",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("runtime_reference", sa.String(), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_acknowledgment LIMIT 1")).first():
        raise RuntimeError("Cannot discard app acknowledgment history")
    op.drop_table("app_execution_acknowledgment")
