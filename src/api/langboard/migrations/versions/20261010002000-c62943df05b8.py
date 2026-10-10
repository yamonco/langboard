"""Persist approved external service app declarations."""

import sqlalchemy as sa
from alembic import op


revision = "c62943df05b8"
down_revision = "b51832cfe4a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_definition",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("declaration", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
    )
    op.create_index("ix_app_definition_key", "app_definition", ["key"], unique=True)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_definition LIMIT 1")).first():
        raise RuntimeError("Cannot discard approved app declarations")
    op.drop_table("app_definition")
