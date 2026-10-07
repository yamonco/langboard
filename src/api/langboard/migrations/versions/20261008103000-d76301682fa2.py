"""Durable bounded GitHub lifecycle health cursor."""

import sqlalchemy as sa
from alembic import op


revision = "d76301682fa2"
down_revision = "c652f0571e91"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "git_hub_health_job",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), sa.ForeignKey("git_hub_lifecycle_receipt.id"), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("board_after", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("resource_after", sa.String(), nullable=True),
        sa.Column("blocked_boards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.UniqueConstraint("receipt_id", name="uq_github_health_receipt"),
        sa.CheckConstraint(
            "state IN ('pending','processing','completed','blocked','failed')", name="ck_github_health_state"
        ),
    )
    op.create_index("ix_github_health_due", "git_hub_health_job", ["state", "available_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM git_hub_health_job LIMIT 1")).first():
        raise RuntimeError("Cannot discard GitHub health jobs")
    op.drop_index("ix_github_health_due", table_name="git_hub_health_job")
    op.drop_table("git_hub_health_job")
