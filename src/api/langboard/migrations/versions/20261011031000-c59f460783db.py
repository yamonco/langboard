"""Persist accepted external app execution requests without fabricating runtime state."""

import sqlalchemy as sa
from alembic import op


revision = "c59f460783db"
down_revision = "b48e359672ca"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_execution_request",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("app_key", sa.String(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("authority", sa.JSON(), nullable=False),
        sa.UniqueConstraint("card_id", "generation", name="uq_app_execution_request_generation"),
    )
    op.create_index("ix_app_execution_request_project_id", "app_execution_request", ["project_id"])
    op.create_index("ix_app_execution_request_card_id", "app_execution_request", ["card_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_execution_request LIMIT 1")).first():
        raise RuntimeError("Cannot discard app execution request history")
    op.drop_table("app_execution_request")
