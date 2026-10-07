"""Persist secret operation audit without credential payloads."""

import sqlalchemy as sa
from alembic import op


revision = "932fcd24eb68"
down_revision = "820ebc13da57"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_reference_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_id", sa.BigInteger(), sa.ForeignKey("secret_reference.id"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_uid", sa.String(), nullable=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column("reference_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created','resolved','renamed','moved','revoked')", name="ck_secret_reference_audit_action"
        ),
    )
    op.create_index("ix_secret_reference_audit_reference_id", "secret_reference_audit", ["reference_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM secret_reference_audit LIMIT 1")).first():
        raise RuntimeError("Cannot discard secret operation audit")
    op.drop_index("ix_secret_reference_audit_reference_id", table_name="secret_reference_audit")
    op.drop_table("secret_reference_audit")
