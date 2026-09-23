"""Track ready transitions and queue execution events atomically.

Revision ID: 71df4c6a9b20
Revises: b62e31c4a709
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from langboard_shared.core.db.ColumnTypes import SnowflakeIDType


revision: str = "71df4c6a9b20"
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
        "card_execution_readiness",
        sa.Column("card_id", SnowflakeIDType, sa.ForeignKey("card.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("is_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "execution_outbox",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", SnowflakeIDType, nullable=False),
        sa.Column("card_id", SnowflakeIDType, nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("card_id", "execution_generation", name="uq_execution_outbox_card_generation"),
    )
    op.create_index(
        "ix_execution_outbox_pending",
        "execution_outbox",
        ["occurred_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.execute(
        """
        CREATE FUNCTION execution_recheck_card(p_card_id bigint) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            c card%ROWTYPE;
            b project_execution_binding%ROWTYPE;
            previous_ready boolean;
            current_generation integer;
            now_ready boolean := false;
            queued_id uuid;
        BEGIN
            SELECT * INTO c FROM card WHERE id = p_card_id;
            IF NOT FOUND THEN RETURN; END IF;
            SELECT * INTO b FROM project_execution_binding WHERE project_id = c.project_id;
            IF NOT FOUND OR NOT b.is_enabled THEN
                UPDATE card_execution_readiness SET is_ready = false, updated_at = now()
                    WHERE card_id = p_card_id AND is_ready = true;
                RETURN;
            END IF;
            INSERT INTO card_execution_readiness(card_id) VALUES (p_card_id)
                ON CONFLICT (card_id) DO NOTHING;
            SELECT is_ready, execution_generation INTO previous_ready, current_generation
                FROM card_execution_readiness WHERE card_id = p_card_id FOR UPDATE;
            IF b.prerequisite_relationship_type_id IS NOT NULL
               AND b.webhook_id IS NOT NULL
               AND b.events::jsonb ? 'io.langboard.work.ready.v1'
               AND c.deleted_at IS NULL AND c.archived_at IS NULL AND c.source_type IS NULL
               AND b.column_semantic_ids ->> (c.project_column_id::text) = 'ready'
               AND EXISTS (
                   SELECT 1 FROM project_column target_column
                   WHERE target_column.id = c.project_column_id
                     AND target_column.deleted_at IS NULL AND NOT target_column.is_archive
               )
               AND EXISTS (
                   SELECT 1 FROM webhook_setting w WHERE w.id = b.webhook_id
                     AND w.secret_id IS NOT NULL
                     AND w.events::jsonb ? 'io.langboard.work.ready.v1'
               )
               AND NOT EXISTS (
                   SELECT 1 FROM card_relationship r
                   LEFT JOIN card prerequisite ON prerequisite.id = r.card_id_parent
                   WHERE r.card_id_child = c.id
                     AND r.relationship_type_id = b.prerequisite_relationship_type_id
                     AND (
                         prerequisite.id IS NULL OR prerequisite.deleted_at IS NOT NULL
                         OR prerequisite.archived_at IS NOT NULL
                         OR b.column_semantic_ids ->> (prerequisite.project_column_id::text)
                            IS DISTINCT FROM 'terminal'
                     )
               )
            THEN
                now_ready := true;
            END IF;
            IF now_ready = previous_ready THEN RETURN; END IF;
            IF now_ready THEN
                current_generation := current_generation + 1;
                UPDATE card_execution_readiness
                    SET is_ready = true, execution_generation = current_generation, updated_at = now()
                    WHERE card_id = p_card_id;
                INSERT INTO execution_outbox(project_id, card_id, execution_generation)
                    VALUES (c.project_id, c.id, current_generation) RETURNING id INTO queued_id;
                PERFORM pg_notify('langboard_execution_outbox', queued_id::text);
            ELSE
                UPDATE card_execution_readiness
                    SET is_ready = false, updated_at = now() WHERE card_id = p_card_id;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION execution_card_changed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE dependent record;
        BEGIN
            PERFORM execution_recheck_card(NEW.id);
            FOR dependent IN SELECT card_id_child FROM card_relationship
                WHERE card_id_parent = NEW.id
            LOOP
                PERFORM execution_recheck_card(dependent.card_id_child);
            END LOOP;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER card_execution_changed
            AFTER INSERT OR UPDATE ON card DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION execution_card_changed();
        """
    )
    op.execute(
        """
        CREATE FUNCTION execution_relationship_changed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE child_id bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN child_id := OLD.card_id_child;
            ELSE child_id := NEW.card_id_child; END IF;
            PERFORM execution_recheck_card(child_id);
            IF TG_OP = 'UPDATE' AND OLD.card_id_child IS DISTINCT FROM NEW.card_id_child THEN
                PERFORM execution_recheck_card(OLD.card_id_child);
            END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER relationship_execution_changed
            AFTER INSERT OR UPDATE OR DELETE ON card_relationship DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION execution_relationship_changed();
        """
    )
    op.execute(
        """
        CREATE FUNCTION execution_column_changed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE changed_card record;
        BEGIN
            FOR changed_card IN SELECT id FROM card WHERE project_column_id = NEW.id
            LOOP
                PERFORM execution_recheck_card(changed_card.id);
            END LOOP;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER column_execution_changed
            AFTER UPDATE ON project_column DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION execution_column_changed();
        """
    )
    op.execute(
        """
        CREATE FUNCTION execution_binding_changed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE changed_card record;
        BEGIN
            FOR changed_card IN SELECT id FROM card WHERE project_id = NEW.project_id
            LOOP
                PERFORM execution_recheck_card(changed_card.id);
            END LOOP;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER binding_execution_changed
            AFTER INSERT OR UPDATE ON project_execution_binding DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION execution_binding_changed();
        """
    )


def downgrade() -> None:
    for trigger, table in (
        ("binding_execution_changed", "project_execution_binding"),
        ("column_execution_changed", "project_column"),
        ("relationship_execution_changed", "card_relationship"),
        ("card_execution_changed", "card"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for function in (
        "execution_binding_changed",
        "execution_column_changed",
        "execution_relationship_changed",
        "execution_card_changed",
        "execution_recheck_card",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function} CASCADE")
    op.drop_index("ix_execution_outbox_pending", table_name="execution_outbox")
    op.drop_table("execution_outbox")
    op.drop_table("card_execution_readiness")
    op.drop_column("project_execution_binding", "webhook_id")
    op.drop_column("project_execution_binding", "prerequisite_relationship_type_id")
    op.drop_column("project_execution_binding", "column_semantic_ids")
