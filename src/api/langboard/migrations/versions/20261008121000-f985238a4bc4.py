"""Append-only resource-scoped App Signal evidence."""
import sqlalchemy as sa
from alembic import op


revision = "f985238a4bc4"
down_revision = "e87412793ab3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_signal",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("app_resource_binding.id"), nullable=False),
        *[sa.Column(name, sa.String(), nullable=False) for name in (
            "provider", "event_id", "event_type", "occurred_at", "external_id", "outcome", "commit_sha", "payload_digest",
        )],
        sa.UniqueConstraint("resource_id", "event_id", name="uq_app_signal_resource_event"),
    )
    op.create_index("ix_app_signal_resource_id", "app_signal", ["resource_id", "id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM app_signal LIMIT 1")).first():
        raise RuntimeError("Cannot discard App Signal evidence")
    op.drop_index("ix_app_signal_resource_id", table_name="app_signal")
    op.drop_table("app_signal")
