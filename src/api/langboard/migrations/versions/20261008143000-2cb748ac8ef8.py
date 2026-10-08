"""Persist the operator's global SCIM employee membership selection."""

import sqlalchemy as sa
from alembic import op


revision = "2cb748ac8ef8"
down_revision = "1ba745ac6de6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_membership_policy",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("group_uids", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("employee_membership_policy")
