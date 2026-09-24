"""Real PostgreSQL proof of atomic readiness transitions without DB triggers."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.tasks.webhooks.ExecutionReadinessUow import (  # noqa: E402
    current_execution,
    execution_readiness_uow,
)


DATABASE_URL = os.getenv("LANGBOARD_OUTBOX_TEST_DATABASE_URL")
MIGRATION = Path(__file__).parents[2] / "langboard/migrations/versions/20260924180000-c7e2b4a091dd.py"
EVENT = "io.langboard.work.ready.v1"


@pytest.mark.skipif(not DATABASE_URL, reason="dedicated PostgreSQL proof URL not set")
def test_application_uow_emits_only_ready_edges_and_freezes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("execution_readiness_uow_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"execution_uow_{uuid4().hex}"
    admin = create_engine(DATABASE_URL)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    enqueued: list[str] = []
    from langboard_shared.tasks.webhooks import ExecutionOutboxTask

    monkeypatch.setattr(ExecutionOutboxTask, "execution_outbox_task", enqueued.append)
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
                "CREATE TABLE card_execution_readiness (card_id bigint PRIMARY KEY, is_ready boolean NOT NULL DEFAULT false, "
                "execution_generation integer NOT NULL DEFAULT 0, updated_at timestamptz DEFAULT now())",
                "CREATE TABLE execution_outbox (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id bigint, "
                "card_id bigint, execution_generation integer, occurred_at timestamptz, event_type text, "
                "payload_json jsonb, state text DEFAULT 'pending', last_error text, "
                "CONSTRAINT uq_execution_outbox_card_generation UNIQUE(card_id, execution_generation))",
            ):
                connection.execute(text(statement))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(
                text("INSERT INTO project_column VALUES (20, NULL, false), (21, NULL, false), (22, NULL, false)")
            )
            connection.execute(
                text("INSERT INTO webhook_setting VALUES (40, 50, CAST(:events AS jsonb))"),
                {"events": f'["{EVENT}"]'},
            )
            connection.execute(
                text(
                    "INSERT INTO project_execution_binding VALUES "
                    "(8, 7, '2026-09-24T00:00:00+00:00', true, 30, 40, 'hook-40', "
                    "CAST(:events AS jsonb), CAST(:semantics AS jsonb))"
                ),
                {"events": f'["{EVENT}"]', "semantics": '{"20":"ready","21":"terminal"}'},
            )
            connection.execute(
                text(
                    "INSERT INTO card VALUES "
                    "(100, 7, 22, NULL, NULL, NULL, 'Before', '2026-09-24T00:00:00+00:00'), "
                    "(101, 7, 22, NULL, NULL, NULL, 'Parent', '2026-09-24T00:00:00+00:00'), "
                    "(102, 7, 22, NULL, NULL, NULL, 'Child', '2026-09-24T00:00:00+00:00')"
                )
            )
            connection.execute(text("INSERT INTO project_label VALUES (9, 'backend')"))
            connection.execute(text("INSERT INTO card_assigned_project_label VALUES (100, 9)"))
            connection.execute(text("INSERT INTO card_assigned_user VALUES (100, 123)"))
            connection.execute(text("INSERT INTO card_relationship VALUES (101, 102, 30)"))

        with execution_readiness_uow() as execution:
            execution.watch([100])
            execution.db.exec(text("UPDATE card SET project_column_id = 20 WHERE id = 100"))
        assert current_execution(100)[1:] == (True, 1)
        with engine.begin() as connection:
            first = connection.execute(
                text("SELECT payload_json, execution_generation FROM execution_outbox WHERE card_id = 100")
            ).one()
            assert first[1] == 1
            assert first[0]["title"] == "Before"
            assert first[0]["labels"] == ["backend"]
            assert first[0]["assignee_ids"] == [123]
            assert first[0]["webhook_uid"] == "hook-40"
            assert first[0]["binding_id"] == "8"
            connection.execute(text("UPDATE card SET title = 'After' WHERE id = 100"))
        with execution_readiness_uow() as execution:
            execution.watch([100])
            execution.db.exec(text("UPDATE card SET project_column_id = 22 WHERE id = 100"))
        assert current_execution(100)[1:] == (False, 1)
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT state FROM execution_outbox WHERE card_id = 100 AND execution_generation = 1")
                ).scalar_one()
                == "superseded"
            )
        with execution_readiness_uow() as execution:
            execution.watch([100])
            execution.db.exec(text("UPDATE card SET project_column_id = 20 WHERE id = 100"))
        with execution_readiness_uow() as execution:
            execution.watch([102])
            execution.db.exec(text("UPDATE card SET project_column_id = 20 WHERE id = 102"))
        assert current_execution(102)[1:] == (False, 0)
        with execution_readiness_uow() as execution:
            execution.watch_card_and_dependents(101)
            execution.db.exec(text("UPDATE card SET project_column_id = 21 WHERE id = 101"))
        assert current_execution(102)[1:] == (True, 1)
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT card_id, execution_generation, payload_json FROM execution_outbox "
                    "ORDER BY card_id, execution_generation"
                )
            ).all()
            assert [(row[0], row[1]) for row in rows] == [(100, 1), (100, 2), (102, 1)]
            assert rows[0][2]["title"] == "Before"
            assert rows[1][2]["title"] == "After"
            assert len(enqueued) == 3
        with execution_readiness_uow() as execution:
            execution.watch([100])
            execution.db.exec(text("UPDATE card SET project_column_id = 22 WHERE id = 100"))
        with pytest.raises(ValueError):
            with execution_readiness_uow() as execution:
                execution.watch([100])
                execution.db.exec(text("UPDATE card SET project_column_id = 20 WHERE id = 100"))
                raise ValueError("rollback")
        assert current_execution(100)[1:] == (False, 2)
        assert len(enqueued) == 3
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()
