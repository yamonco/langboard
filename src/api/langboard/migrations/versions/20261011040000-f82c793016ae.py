"""Persist app delivery lease fencing without scheduling external execution."""
import sqlalchemy as sa
from alembic import op


revision = "f82c793016ae"
down_revision = "e71b682905fd"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_execution_outbox", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_execution_outbox", sa.Column("claim_token", sa.String(), nullable=True))
    op.add_column("app_execution_outbox", sa.Column("last_error", sa.String(), nullable=True))
    op.add_column("app_execution_outbox", sa.Column("delivery_history", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_outbox WHERE attempt_count > 0 LIMIT 1")).first():
        raise RuntimeError("Cannot discard app delivery claim history")
    for name in ("delivery_history", "last_error", "claim_token", "lease_until"):
        op.drop_column("app_execution_outbox", name)
