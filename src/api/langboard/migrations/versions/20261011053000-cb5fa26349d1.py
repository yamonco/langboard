"""Preserve app-reported start evidence after connection or card removal."""

import sqlalchemy as sa
from alembic import op

revision = "cb5fa26349d1"
down_revision = "ba4e915238c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_execution_start",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("acknowledgment_id", sa.BigInteger(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("runtime_reference", sa.String(), nullable=False),
        sa.Column("execution_reference", sa.String(), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_start LIMIT 1")).first():
        raise RuntimeError("Cannot discard app-reported start evidence")
    op.drop_table("app_execution_start")
