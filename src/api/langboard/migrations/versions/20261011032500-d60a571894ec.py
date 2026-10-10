"""Persist independent app event intent atomically with accepted execution requests."""

import sqlalchemy as sa
from alembic import op


revision = "d60a571894ec"
down_revision = "c59f460783db"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_execution_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("request_id", "event_type", name="uq_app_execution_outbox_request_event"),
        sa.CheckConstraint(
            "state IN ('pending','delivering','delivered','blocked','failed')",
            name=op.f("ck_app_execution_outbox_state"),
        ),
    )
    op.create_index("ix_app_execution_outbox_request_id", "app_execution_outbox", ["request_id"])
    op.create_index("ix_app_execution_outbox_project_id", "app_execution_outbox", ["project_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_outbox LIMIT 1")).first():
        raise RuntimeError("Cannot discard app execution event history")
    op.drop_table("app_execution_outbox")
