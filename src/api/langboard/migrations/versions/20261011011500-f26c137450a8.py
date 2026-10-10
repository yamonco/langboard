"""Store hashes of explicitly issued inbound app connection credentials."""

import sqlalchemy as sa
from alembic import op


revision = "f26c137450a8"
down_revision = "e15b02634f97"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_connection_credential",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        sa.Column("issued_by", sa.BigInteger(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("identity_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_connection_credential_connection_id", "app_connection_credential", ["connection_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_connection_credential LIMIT 1")).first():
        raise RuntimeError("Cannot discard app credential history")
    op.drop_table("app_connection_credential")
