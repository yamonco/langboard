"""Stable private secret references without exposing provider locators."""

import sqlalchemy as sa
from alembic import op


revision = "820ebc13da57"
down_revision = "719dab02cf46"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_reference",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scope", "scope_id", "name", name="uq_secret_reference_scope_name"),
        sa.CheckConstraint("scope IN ('personal','project','workspace')", name="ck_secret_reference_scope"),
        sa.CheckConstraint("state IN ('active','revoked')", name="ck_secret_reference_state"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM secret_reference LIMIT 1")).first():
        raise RuntimeError("Cannot discard persisted secret references")
    op.drop_table("secret_reference")
