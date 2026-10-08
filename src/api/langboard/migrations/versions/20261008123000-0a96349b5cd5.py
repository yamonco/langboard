"""Durable check delivery evidence and bounded dispatch cursor."""
import sqlalchemy as sa
from alembic import op


revision = "0a96349b5cd5"
down_revision = "f985238a4bc4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "git_hub_signal_delivery",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), sa.ForeignKey("app_connection.id"), nullable=False),
        *[sa.Column(name, sa.String(), nullable=False) for name in (
            "connection_revision", "event_id", "installation_id", "account_id", "repository_id",
        )],
        sa.Column("secret_revision", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("resource_after", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("resource_upper", sa.BigInteger(), nullable=False),
        sa.Column("skipped_resources", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.UniqueConstraint("connection_id", "event_id", name="uq_github_signal_delivery"),
        sa.CheckConstraint("state IN ('pending','processing','completed','blocked','failed')", name="ck_github_signal_state"),
    )
    op.create_index("ix_github_signal_due", "git_hub_signal_delivery", ["state", "available_at"])
    op.create_index("ix_app_resource_signal_lookup", "app_resource_binding", ["connection_id", "resource_type", "external_resource_id", "id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM git_hub_signal_delivery LIMIT 1")).first():
        raise RuntimeError("Cannot discard GitHub Signal delivery evidence")
    op.drop_index("ix_app_resource_signal_lookup", table_name="app_resource_binding")
    op.drop_index("ix_github_signal_due", table_name="git_hub_signal_delivery")
    op.drop_table("git_hub_signal_delivery")
