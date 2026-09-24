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


@pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL proof URL not set")
def test_delivery_lifecycle_reaches_terminal_states_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the converged one-task delivery: delivered, failed, and crash recovery."""
    from asyncio import run as asyncio_run
    from types import SimpleNamespace
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.tasks.webhooks import ExecutionOutboxWorker as worker

    schema = f"outbox_lifecycle_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)

    outcomes: list[Exception | None] = []

    async def fake_post(model, webhook_uid):
        if outcomes:
            failure = outcomes.pop(0)
            if failure is not None:
                raise failure

    monkeypatch.setattr(worker, "post_signed_webhook", fake_post)
    monkeypatch.setattr(worker, "binding_invalid_reasons", lambda binding, event: [])
    try:
        with engine.begin() as connection:
            for statement in (
                "CREATE TABLE project_column (id bigint PRIMARY KEY, deleted_at timestamptz, is_archive boolean NOT NULL)",
                "CREATE TABLE webhook_setting (id bigint PRIMARY KEY, secret_id bigint, events jsonb NOT NULL)",
                "CREATE TABLE project_execution_binding (id bigint PRIMARY KEY, project_id bigint UNIQUE, "
                "updated_at timestamptz NOT NULL, is_enabled boolean NOT NULL, "
                "prerequisite_relationship_type_id bigint, webhook_id bigint, webhook_uid text, events jsonb NOT NULL, "
                "column_semantic_ids jsonb NOT NULL)",
                "CREATE TABLE card (id bigint PRIMARY KEY, project_id bigint, project_column_id bigint, "
                "deleted_at timestamptz, archived_at timestamptz, source_type text, title text, updated_at timestamptz)",
                "CREATE TABLE card_relationship (card_id_parent bigint, card_id_child bigint, relationship_type_id bigint)",
                "CREATE TABLE project_label (id bigint PRIMARY KEY, name text)",
                "CREATE TABLE card_assigned_project_label (card_id bigint, project_label_id bigint)",
                "CREATE TABLE card_assigned_user (card_id bigint, user_id bigint)",
                "CREATE TABLE card_execution_generation (card_id bigint PRIMARY KEY, execution_generation integer "
                "NOT NULL DEFAULT 0)",
                "CREATE TABLE execution_outbox (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id bigint, "
                "card_id bigint, execution_generation integer, occurred_at timestamptz DEFAULT now(), event_type text, "
                "payload_json jsonb, state text DEFAULT 'pending', last_error text, processed_at timestamptz, "
                "attempt_count integer NOT NULL DEFAULT 0, lease_until timestamptz, "
                "CONSTRAINT uq_execution_outbox_card_generation UNIQUE(card_id, execution_generation))",
            ):
                connection.execute(text(statement))
            connection.execute(text("INSERT INTO project_column VALUES (20, NULL, false)"))
            connection.execute(
                text("INSERT INTO webhook_setting VALUES (40, 50, CAST(:events AS jsonb))"),
                {"events": '["io.langboard.work.ready.v1"]'},
            )
            connection.execute(
                text(
                    "INSERT INTO project_execution_binding VALUES "
                    "(8, 7, '2026-09-24T00:00:00+00:00', true, 30, 40, 'hook-40', "
                    "CAST(:events AS jsonb), CAST(:semantics AS jsonb))"
                ),
                {"events": '["io.langboard.work.ready.v1"]', "semantics": '{"20":"ready"}'},
            )
            connection.execute(
                text(
                    "INSERT INTO card VALUES "
                    "(100, 7, 20, NULL, NULL, NULL, 'Task', '2026-09-24T00:00:00+00:00')"
                )
            )
            connection.execute(
                text("INSERT INTO card_execution_generation VALUES (100, 3)")
            )
            connection.execute(
                text(
                    "INSERT INTO execution_outbox(project_id, card_id, execution_generation, event_type, payload_json) "
                    "VALUES (7, 100, 3, 'io.langboard.work.ready.v1', CAST(:payload AS jsonb))"
                ),
                {
                    "payload": (
                        '{"title": "Task", "labels": [], "assignee_ids": [], '
                        '"source_revision": "2026-09-24T00:00:00+00:00", "binding_id": "8", '
                        '"binding_revision": "2026-09-24T00:00:00+00:00", "webhook_uid": "hook-40"}'
                    )
                },
            )
        binding_row = None
        with engine.connect() as connection:
            binding_row = connection.execute(
                text("SELECT id, updated_at, webhook_uid FROM project_execution_binding WHERE id = 8")
            ).one()
        frozen_binding = SimpleNamespace(id=binding_row[0], updated_at=binding_row[1], webhook_uid=binding_row[2])
        monkeypatch.setattr(worker, "binding_for_project", lambda uid: frozen_binding)

        # Completion 1: success reaches the terminal delivered state.
        assert asyncio_run(worker.drain_one())
        with engine.connect() as connection:
            state, attempts, lease = connection.execute(
                text("SELECT state, attempt_count, lease_until FROM execution_outbox WHERE card_id = 100")
            ).one()
        assert state == "delivered"
        assert attempts == 1
        assert lease is not None

        # Completion 2: HTTP failures retry with a bounded attempt budget, then fail terminally.
        outcomes.extend([RuntimeError("500")] * worker.MAX_DELIVERY_ATTEMPTS)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE execution_outbox SET state = 'pending', attempt_count = 0, lease_until = NULL")
            )
        for _ in range(worker.MAX_DELIVERY_ATTEMPTS):
            with pytest.raises(worker.ExecutionDeliveryFailed):
                asyncio_run(worker.drain_one())
            with engine.connect() as connection:
                state, attempts, lease = connection.execute(
                    text("SELECT state, attempt_count, lease_until FROM execution_outbox WHERE card_id = 100")
                ).one()
            assert state == "pending"
            assert lease is None
        assert asyncio_run(worker.drain_one())
        with engine.connect() as connection:
            state, error, attempts = connection.execute(
                text("SELECT state, last_error, attempt_count FROM execution_outbox WHERE card_id = 100")
            ).one()
        assert state == "failed"
        assert error == "delivery_attempts_exhausted"
        assert attempts == worker.MAX_DELIVERY_ATTEMPTS

        # Completion 3: a worker crash between claim and HTTP leaves a stale lease that recovery re-drains.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE execution_outbox SET state = 'pending', last_error = NULL, attempt_count = 0, "
                    "lease_until = NULL"
                )
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE execution_outbox SET state = 'delivering', attempt_count = 1, "
                    "lease_until = now() - interval '1 second'"
                )
            )
        assert asyncio_run(worker.drain_one())
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT state FROM execution_outbox WHERE card_id = 100")).scalar_one()
                == "delivered"
            )

        # A live lease is not re-claimed, bounding duplicate concurrent delivery.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE execution_outbox SET state = 'delivering', attempt_count = 1, "
                    "lease_until = now() + interval '1 minute', last_error = NULL"
                )
            )
        assert not asyncio_run(worker.drain_one())
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT state FROM execution_outbox WHERE card_id = 100")).scalar_one()
                == "delivering"
            )

        # Operator recovery re-queues terminal failures with a fresh attempt budget.
        with engine.begin() as connection:
            connection.execute(text("UPDATE execution_outbox SET state = 'failed', last_error = 'delivery_attempts_exhausted'"))
        assert worker.reconcile(_short_code_for(7)) == 1
        with engine.connect() as connection:
            state, attempts = connection.execute(
                text("SELECT state, attempt_count FROM execution_outbox WHERE card_id = 100")
            ).one()
        assert state == "pending"
        assert attempts == 0
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()


def _short_code_for(project_id: int) -> str:
    """Convert an internal project id to its public short code for reconcile."""
    from langboard_shared.core.types import SnowflakeID

    return SnowflakeID(project_id).to_short_code()
