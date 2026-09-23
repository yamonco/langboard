"""Freeze execution event data when the ready transition commits.

Revision ID: 8e9c4a2d51b0
Revises: 71df4c6a9b20
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "8e9c4a2d51b0"
down_revision: Union[str, Sequence[str], None] = "71df4c6a9b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_outbox",
        sa.Column("event_type", sa.String(80), nullable=False, server_default="io.langboard.work.ready.v1"),
    )
    op.add_column("execution_outbox", sa.Column("payload_json", JSONB(), nullable=True))
    # Older pointer-only rows cannot be reconstructed without inventing their
    # commit-time card snapshot. Keep them visible for manual diagnosis.
    op.execute(
        "UPDATE execution_outbox SET state = 'blocked', last_error = 'snapshot_unavailable' "
        "WHERE payload_json IS NULL"
    )
    op.execute(
        """
        CREATE FUNCTION execution_outbox_freeze() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE c card%ROWTYPE;
        BEGIN
            SELECT * INTO c FROM card WHERE id = NEW.card_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'execution outbox card missing: %', NEW.card_id; END IF;
            UPDATE execution_outbox SET payload_json = jsonb_build_object(
                'title', c.title,
                'labels', COALESCE((
                    SELECT jsonb_agg(label.name ORDER BY label.name)
                    FROM card_assigned_project_label assigned
                    JOIN project_label label ON label.id = assigned.project_label_id
                    WHERE assigned.card_id = c.id
                ), '[]'::jsonb),
                'assignee_ids', COALESCE((
                    SELECT jsonb_agg(assigned.user_id ORDER BY assigned.user_id)
                    FROM card_assigned_user assigned WHERE assigned.card_id = c.id
                ), '[]'::jsonb),
                'source_revision', c.updated_at,
                'direct_blocker_uids', '[]'::jsonb
            ) WHERE id = NEW.id;
            RETURN NULL;
        END $$;
        CREATE TRIGGER execution_outbox_freeze_insert
            AFTER INSERT ON execution_outbox
            FOR EACH ROW EXECUTE FUNCTION execution_outbox_freeze();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS execution_outbox_freeze_insert ON execution_outbox")
    op.execute("DROP FUNCTION IF EXISTS execution_outbox_freeze()")
    op.drop_column("execution_outbox", "payload_json")
    op.drop_column("execution_outbox", "event_type")
