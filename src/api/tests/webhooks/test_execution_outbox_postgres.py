"""Real PostgreSQL proof that an execution event keeps its commit-time data."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv("LANGBOARD_OUTBOX_TEST_DATABASE_URL")
MIGRATION = (
    Path(__file__).parents[2]
    / "langboard/migrations/versions/20260924150000-8e9c4a2d51b0.py"
)


@pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL proof URL not set")
def test_outbox_snapshot_survives_card_changes_and_new_connection() -> None:
    spec = importlib.util.spec_from_file_location("execution_outbox_snapshot_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"outbox_proof_{uuid4().hex}"
    engine = create_engine(DATABASE_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            connection.execute(text("CREATE TABLE card (id bigint PRIMARY KEY, project_id bigint, title text, updated_at timestamptz)"))
            connection.execute(text("CREATE TABLE project_label (id bigint PRIMARY KEY, name text)"))
            connection.execute(text("CREATE TABLE card_assigned_project_label (card_id bigint, project_label_id bigint)"))
            connection.execute(text("CREATE TABLE card_assigned_user (card_id bigint, user_id bigint)"))
            connection.execute(text(
                "CREATE TABLE execution_outbox (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                "project_id bigint, card_id bigint, execution_generation integer, "
                "occurred_at timestamptz DEFAULT now(), state varchar(16) DEFAULT 'pending', "
                "last_error varchar(80), processed_at timestamptz)"
            ))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(text(
                "INSERT INTO card VALUES (42, 7, 'Before', '2026-09-24T00:00:00+00:00')"
            ))
            connection.execute(text("INSERT INTO project_label VALUES (9, 'backend'), (10, 'urgent')"))
            connection.execute(text("INSERT INTO card_assigned_project_label VALUES (42, 9)"))
            connection.execute(text("INSERT INTO card_assigned_user VALUES (42, 123)"))
            event_id = connection.execute(text(
                "INSERT INTO execution_outbox(project_id, card_id, execution_generation) "
                "VALUES (7, 42, 1) RETURNING id"
            )).scalar_one()
            snapshot = connection.execute(text(
                "SELECT payload_json FROM execution_outbox WHERE id = :event_id"
            ), {"event_id": event_id}).scalar_one()
            assert snapshot["title"] == "Before"
            assert snapshot["labels"] == ["backend"]
            assert snapshot["assignee_ids"] == [123]
            assert snapshot["source_revision"].startswith("2026-09-24T00:00:00")
            connection.execute(text("UPDATE card SET title = 'After' WHERE id = 42"))
            connection.execute(text("DELETE FROM card_assigned_project_label WHERE card_id = 42"))
            connection.execute(text("INSERT INTO card_assigned_project_label VALUES (42, 10)"))
            connection.execute(text("DELETE FROM card_assigned_user WHERE card_id = 42"))
        with engine.begin() as restarted_worker_connection:
            restarted_worker_connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            assert restarted_worker_connection.execute(text(
                "SELECT payload_json FROM execution_outbox WHERE id = :event_id"
            ), {"event_id": event_id}).scalar_one() == snapshot
            assert restarted_worker_connection.execute(text(
                "SELECT state FROM execution_outbox WHERE id = :event_id"
            ), {"event_id": event_id}).scalar_one() == "pending"
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
