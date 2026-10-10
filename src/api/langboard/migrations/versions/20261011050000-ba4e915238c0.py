"""Keep runtime-specific permits and stop history after connection deletion."""

import sqlalchemy as sa
from alembic import op


revision = "ba4e915238c0"
down_revision = "a93d804127bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_execution_lease",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("acknowledgment_id", sa.BigInteger(), nullable=False),
        sa.Column("runtime_token_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.CheckConstraint("state IN ('authorized','stop_requested','stopped')", name="ck_app_execution_lease_state"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_lease LIMIT 1")).first():
        raise RuntimeError("Cannot discard runtime permit history")
    op.drop_table("app_execution_lease")
