"""Install the execution outbox schema in its final shape.

Revision ID: 7ad15b1d0b70
Revises: b62e31c4a709

Squash of the branch-only execution migrations (71df4c6a9b20,
8e9c4a2d51b0, c7e2b4a091dd, d4f92c7b180a, a24ec4b7d19f, b3d5e7f9a1c2)
that never reached the public main branch. The interim history created a
database trigger mini-engine for readiness transitions and dropped it again
one migration later, so installing it verbatim would make every fresh
install create and drop transient functions, triggers, and columns.

This single migration creates only the final state:

- ``project_execution_binding`` column semantics and webhook linkage
- ``card_execution_generation`` readiness generation counters
- ``execution_outbox`` with the converged delivery columns
- ``execution_receipt`` and ``execution_checklist_projection``

Databases that already applied the interim branch chain (for example a
canary built from review branches) must be rebuilt or reconciled with a
branch-only script before adopting this history; the public migration
history keeps the final shape only.
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "7ad15b1d0b70"
down_revision: Union[str, Sequence[str], None] = "b62e31c4a709"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_execution_binding",
        sa.Column("column_semantic_ids", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column(
        "project_execution_binding",
        sa.Column("prerequisite_relationship_type_id", SnowflakeIDType, nullable=True),
    )
    op.add_column(
        "project_execution_binding",
        sa.Column("webhook_id", SnowflakeIDType, nullable=True),
    )
    op.create_table(
        "card_execution_generation",
        sa.Column("card_id", SnowflakeIDType, sa.ForeignKey("card.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("execution_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "execution_outbox",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", SnowflakeIDType, nullable=False),
        sa.Column("card_id", SnowflakeIDType, nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(80), nullable=False, server_default="io.langboard.work.ready.v1"),
        sa.Column("payload_json", JSONB(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("card_id", "execution_generation", name="uq_execution_outbox_card_generation"),
    )
    op.create_index(
        "ix_execution_outbox_pending",
        "execution_outbox",
        ["occurred_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "execution_receipt",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(240), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("card_id", "execution_generation", name="uq_execution_receipt_card_generation"),
    )
    op.create_table(
        "execution_checklist_projection",
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("item_uid", sa.String(100), nullable=False),
        sa.Column("evidence_kind", sa.String(100), nullable=False),
        sa.Column("evidence_refs", JSONB(), nullable=False),
        sa.Column("is_checked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("card_id", "execution_generation", "item_uid"),
    )


def downgrade() -> None:
    op.drop_table("execution_checklist_projection")
    op.drop_table("execution_receipt")
    op.drop_index("ix_execution_outbox_pending", table_name="execution_outbox")
    op.drop_table("execution_outbox")
    op.drop_table("card_execution_generation")
    op.drop_column("project_execution_binding", "webhook_id")
    op.drop_column("project_execution_binding", "prerequisite_relationship_type_id")
    op.drop_column("project_execution_binding", "column_semantic_ids")
