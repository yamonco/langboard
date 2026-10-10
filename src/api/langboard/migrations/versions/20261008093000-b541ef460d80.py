"""Persist verified GitHub lifecycle delivery provenance."""

import sqlalchemy as sa
from alembic import op


revision = "b541ef460d80"
down_revision = "a430de35fc79"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "git_hub_lifecycle_receipt",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        *[
            sa.Column(name, sa.String(), nullable=False)
            for name in (
                "connection_revision",
                "delivery_id",
                "payload_digest",
                "event",
                "action",
                "app_id",
                "installation_id",
                "account_id",
            )
        ],
        sa.Column("added_repository_ids", sa.JSON(), nullable=False),
        sa.Column("removed_repository_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("connection_id", "delivery_id", name="uq_github_lifecycle_delivery"),
    )
    op.create_index("ix_git_hub_lifecycle_receipt_connection_id", "git_hub_lifecycle_receipt", ["connection_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM git_hub_lifecycle_receipt LIMIT 1")).first():
        raise RuntimeError("Cannot discard GitHub lifecycle receipts")
    op.drop_index("ix_git_hub_lifecycle_receipt_connection_id", table_name="git_hub_lifecycle_receipt")
    op.drop_table("git_hub_lifecycle_receipt")
