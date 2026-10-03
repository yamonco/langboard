import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

# Match application startup before importing execution routes independently.
from langboard_shared.domain.services import DomainService  # noqa: F401


# isort: split
from langboard.routes.board import ExecutionReceiptApi as receipt_api
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.tasks.webhooks import ExecutionReadinessUow as readiness_module


def test_native_receipt_is_idempotent_and_never_writes_user_description(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("LANGBOARD_OUTBOX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL test URL is not configured")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS execution_checklist_projection"))
        connection.execute(text("DROP TABLE IF EXISTS execution_receipt"))
        connection.execute(text("DROP TABLE IF EXISTS execution_outbox"))
        connection.execute(text("DROP TABLE IF EXISTS card_execution_generation"))
        connection.execute(
            text(
                'CREATE TABLE card (id bigint PRIMARY KEY, description text NOT NULL, project_column_id bigint NOT NULL, "order" integer NOT NULL, updated_at timestamptz NOT NULL, deleted_at timestamptz)'
            )
        )
        connection.execute(text("INSERT INTO card VALUES (100, 'user-authored markdown', 1, 1, now(), NULL)"))
        connection.execute(
            text("""
                INSERT INTO card VALUES
                    (101, 'source before', 1, 0, '2026-09-23T00:00:00Z', NULL),
                    (102, 'source after', 1, 2, '2026-09-23T00:00:00Z', NULL),
                    (103, 'review existing', 2, 0, '2026-09-23T00:00:00Z', NULL),
                    (104, 'source deleted', 1, 99, '2026-09-23T00:00:00Z', now()),
                    (105, 'review deleted', 2, 99, '2026-09-23T00:00:00Z', now())
            """)
        )
        connection.execute(
            text(
                "CREATE TABLE project_column (id bigint PRIMARY KEY, project_id bigint NOT NULL, deleted_at timestamptz, is_archive boolean NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO project_column VALUES (1, 10, NULL, false), (2, 10, NULL, false)"))
        # Baseline binding shape as the public main history leaves it; the
        # install migration adds the semantic id columns on top.
        connection.execute(
            text("CREATE TABLE project_execution_binding (project_id bigint PRIMARY KEY, is_enabled boolean NOT NULL)")
        )
        module = __import__(
            "langboard.migrations.versions.20260924220000-7ad15b1d0b70",
            fromlist=["upgrade"],
        )
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.execute(
            text(
                "INSERT INTO project_execution_binding (project_id, is_enabled, column_semantic_ids) "
                'VALUES (10, true, \'{"1":"ready","2":"review"}\'::jsonb)'
            )
        )
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(
        receipt_api.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: (SimpleNamespace(id=10), SimpleNamespace(id=100)),
    )
    monkeypatch.setattr(receipt_api, "current_execution", lambda card_id, db: (datetime.now(UTC), True, 5))

    @contextmanager
    def receipt_uow():
        with DbSession.atomic() as db:
            yield readiness_module.ExecutionReadinessUow(db)

    monkeypatch.setattr(readiness_module, "_scalar", lambda *args, **kwargs: False)
    monkeypatch.setattr(receipt_api, "execution_readiness_uow", receipt_uow)
    actor = SimpleNamespace(id=44)
    moves = []
    receipt_notifications = []

    def notify_receipt(card):
        with engine.connect() as connection:
            committed = connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar()
        receipt_notifications.append((card.id, committed))

    monkeypatch.setattr(receipt_api.CardPublisher, "execution_receipt_changed", notify_receipt)

    def notify_move(received_actor, project_id, card_id, old_column_id, new_column_id):
        with engine.connect() as connection:
            committed = connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar()
        moves.append((received_actor, project_id, card_id, old_column_id, new_column_id, committed))

    monkeypatch.setattr(receipt_api, "_review_move_notification", lambda *args: lambda: notify_move(*args))
    form = receipt_api.PutExecutionReceiptForm(
        status="success",
        summary="PR submitted",
        artifacts=[{"type": "pull_request", "url": "https://github.com/example/repo/pull/1"}],
        evidence=[{"kind": "pr_submitted", "refs": ["https://github.com/example/repo/pull/1"]}],
        checklist_evidence=[
            {"item_uid": "user-item", "kind": "pr_submitted", "refs": ["https://github.com/example/repo/pull/1"]},
            {"item_uid": "unverified-item", "kind": "manual_note", "refs": ["studio://reports/1"]},
        ],
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    key = "langboard:board:card:5:receipt"
    try:

        @contextmanager
        def failed_receipt_uow():
            with DbSession.atomic() as db:
                yield readiness_module.ExecutionReadinessUow(db)
                raise RuntimeError("receipt transaction failed before commit")

        monkeypatch.setattr(receipt_api, "execution_readiness_uow", failed_receipt_uow)
        with pytest.raises(RuntimeError, match="before commit"):
            receipt_api.put_execution_receipt("board", "card", 5, form, key, actor)
        assert moves == []
        assert receipt_notifications == []
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar() == 0
            assert connection.execute(text("SELECT project_column_id FROM card WHERE id=100")).scalar() == 1
        monkeypatch.setattr(receipt_api, "execution_readiness_uow", receipt_uow)
        first = receipt_api.put_execution_receipt("board", "card", 5, form, key, actor)
        # Simulate a missing derived row after a previous receipt was stored.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM execution_checklist_projection WHERE item_uid='user-item'"))
        retried = form.model_copy(update={"occurred_at": datetime.now(UTC)})
        second = receipt_api.put_execution_receipt("board", "card", 5, retried, key, actor)
        assert json.loads(first.body)["created"] is True
        assert json.loads(second.body)["created"] is False
        assert moves == [(actor, 10, 100, 1, 2, 1)]
        assert receipt_notifications == [(100, 1)]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar() == 1
            projected = connection.execute(
                text("SELECT item_uid, is_checked FROM execution_checklist_projection ORDER BY item_uid")
            ).all()
            assert projected == [("unverified-item", False), ("user-item", True)]
            assert (
                connection.execute(text("SELECT description FROM card WHERE id=100")).scalar()
                == "user-authored markdown"
            )
            assert connection.execute(text("SELECT project_column_id FROM card WHERE id=100")).scalar() == 2
            assert connection.execute(
                text('SELECT id, "order" FROM card WHERE deleted_at IS NULL ORDER BY project_column_id, "order"')
            ).all() == [(101, 0), (102, 1), (103, 0), (100, 1)]
            assert connection.execute(text('SELECT "order" FROM card WHERE id=104')).scalar() == 99
            assert connection.execute(text("SELECT updated_at FROM card WHERE id=102")).scalar() == datetime(
                2026, 9, 23, tzinfo=UTC
            )
        history = receipt_api.receipt_history(100)
        assert len(history) == 1
        assert history[0]["receipt"]["summary"] == "PR submitted"
        assert len(history[0]["checklist_projection"]) == 2
        changed = form.model_copy(update={"summary": "different result"})
        with pytest.raises(receipt_api.ApiException.Conflict_409):
            receipt_api.put_execution_receipt("board", "card", 5, changed, key, actor)
        assert len(moves) == 1
        assert receipt_notifications == [(100, 1)]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar() == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS execution_checklist_projection"))
            connection.execute(text("DROP TABLE IF EXISTS execution_receipt"))
            connection.execute(text("DROP TABLE IF EXISTS execution_outbox"))
            connection.execute(text("DROP TABLE IF EXISTS card_execution_generation"))
            connection.execute(text("DROP TABLE IF EXISTS project_execution_binding"))
            connection.execute(text("DROP TABLE IF EXISTS project_column"))
            connection.execute(text("DROP TABLE IF EXISTS card"))
        engine.dispose()
