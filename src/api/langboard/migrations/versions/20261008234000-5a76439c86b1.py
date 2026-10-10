"""Persistent actor-scoped Signal Inbox card creation receipts."""

import sqlalchemy as sa
from alembic import op


revision = "5a76439c86b1"
down_revision = "2cb748ac8ef8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "card_signal_creation",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("app_resource_binding.id"), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), sa.ForeignKey("card.id"), nullable=False),
        sa.UniqueConstraint(
            "actor_id", "resource_id", "external_id", "commit_sha", name="uq_card_signal_creation_identity"
        ),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM card_signal_creation LIMIT 1")).first():
        raise RuntimeError("Cannot discard Signal Inbox card creation receipts")
    op.drop_table("card_signal_creation")
