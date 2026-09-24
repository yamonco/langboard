"""Move execution readiness ownership from triggers to application UoW.

Revision ID: c7e2b4a091dd
Revises: 8e9c4a2d51b0
"""

from typing import Sequence, Union
from alembic import op


revision: str = "c7e2b4a091dd"
down_revision: Union[str, Sequence[str], None] = "8e9c4a2d51b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old pending rows have no commit-time destination identity. Replaying
    # them against today's binding would redirect a historical event.
    op.execute(
        "UPDATE execution_outbox SET state = 'blocked', last_error = 'destination_unavailable' "
        "WHERE state = 'pending' AND (payload_json IS NULL OR NOT (payload_json ? 'webhook_uid'))"
    )
    for trigger, table in (
        ("binding_execution_changed", "project_execution_binding"),
        ("column_execution_changed", "project_column"),
        ("relationship_execution_changed", "card_relationship"),
        ("card_execution_changed", "card"),
        ("execution_outbox_freeze_insert", "execution_outbox"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for function in (
        "execution_binding_changed",
        "execution_column_changed",
        "execution_relationship_changed",
        "execution_card_changed",
        "execution_recheck_card",
        "execution_outbox_freeze",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function} CASCADE")
    op.drop_column("card_execution_readiness", "is_ready")
    op.drop_column("card_execution_readiness", "updated_at")
    op.rename_table("card_execution_readiness", "card_execution_generation")


def downgrade() -> None:
    raise RuntimeError("Execution readiness cannot safely revert to trigger ownership after application events")
