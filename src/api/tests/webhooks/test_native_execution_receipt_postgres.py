import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.board import ExecutionReceiptApi as receipt_api  # noqa: E402
from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402


def test_native_receipt_is_idempotent_and_never_writes_user_description(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("LANGBOARD_OUTBOX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL test URL is not configured")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS execution_checklist_projection"))
        connection.execute(text("DROP TABLE IF EXISTS execution_receipt"))
        connection.execute(text("CREATE TABLE card (id bigint PRIMARY KEY, description text NOT NULL, project_column_id bigint NOT NULL, \"order\" integer NOT NULL, updated_at timestamptz NOT NULL, deleted_at timestamptz)"))
        connection.execute(text("INSERT INTO card VALUES (100, 'user-authored markdown', 1, 0, now(), NULL)"))
        connection.execute(text("CREATE TABLE project_column (id bigint PRIMARY KEY, project_id bigint NOT NULL, deleted_at timestamptz, is_archive boolean NOT NULL)"))
        connection.execute(text("INSERT INTO project_column VALUES (1, 10, NULL, false), (2, 10, NULL, false)"))
        connection.execute(text("CREATE TABLE project_execution_binding (project_id bigint PRIMARY KEY, is_enabled boolean NOT NULL, column_semantic_ids jsonb NOT NULL)"))
        connection.execute(text("INSERT INTO project_execution_binding VALUES (10, true, '{\"1\":\"ready\",\"2\":\"review\"}'::jsonb)"))
        module = __import__(
            "langboard.migrations.versions.20260924190000-d4f92c7b180a",
            fromlist=["upgrade"],
        )
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        projection_module = __import__(
            "langboard.migrations.versions.20260924200000-a24ec4b7d19f",
            fromlist=["upgrade"],
        )
        monkeypatch.setattr(projection_module, "op", Operations(MigrationContext.configure(connection)))
        projection_module.upgrade()
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(
        receipt_api.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: (SimpleNamespace(id=10), SimpleNamespace(id=100)),
    )
    monkeypatch.setattr(receipt_api, "current_execution", lambda card_id, db: (datetime.now(timezone.utc), True, 5))

    @contextmanager
    def receipt_uow():
        with DbSession.atomic() as db:
            yield SimpleNamespace(db=db, watch=lambda card_id: None)

    monkeypatch.setattr(receipt_api, "execution_readiness_uow", receipt_uow)
    form = receipt_api.PutExecutionReceiptForm(
        status="success",
        summary="PR submitted",
        artifacts=[{"type": "pull_request", "url": "https://github.com/example/repo/pull/1"}],
        evidence=[{"kind": "pr_submitted", "refs": ["https://github.com/example/repo/pull/1"]}],
        checklist_evidence=[
            {"item_uid": "user-item", "kind": "pr_submitted", "refs": ["https://github.com/example/repo/pull/1"]},
            {"item_uid": "unverified-item", "kind": "manual_note", "refs": ["studio://reports/1"]},
        ],
        occurred_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    key = "langboard:board:card:5:receipt"
    try:
        first = receipt_api.put_execution_receipt("board", "card", 5, form, key)
        # Simulate a missing derived row after a previous receipt was stored.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM execution_checklist_projection WHERE item_uid='user-item'"))
        retried = form.model_copy(update={"occurred_at": datetime.now(timezone.utc)})
        second = receipt_api.put_execution_receipt("board", "card", 5, retried, key)
        assert json.loads(first.body)["created"] is True
        assert json.loads(second.body)["created"] is False
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar() == 1
            projected = connection.execute(
                text("SELECT item_uid, is_checked FROM execution_checklist_projection ORDER BY item_uid")
            ).all()
            assert projected == [("unverified-item", False), ("user-item", True)]
            assert connection.execute(text("SELECT description FROM card WHERE id=100")).scalar() == "user-authored markdown"
            assert connection.execute(text("SELECT project_column_id FROM card WHERE id=100")).scalar() == 2
        history = receipt_api.receipt_history(100)
        assert len(history) == 1
        assert history[0]["receipt"]["summary"] == "PR submitted"
        assert len(history[0]["checklist_projection"]) == 2
        changed = form.model_copy(update={"summary": "different result"})
        with pytest.raises(receipt_api.ApiException.Conflict_409):
            receipt_api.put_execution_receipt("board", "card", 5, changed, key)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM execution_receipt")).scalar() == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS execution_checklist_projection"))
            connection.execute(text("DROP TABLE IF EXISTS execution_receipt"))
            connection.execute(text("DROP TABLE IF EXISTS project_execution_binding"))
            connection.execute(text("DROP TABLE IF EXISTS project_column"))
            connection.execute(text("DROP TABLE IF EXISTS card"))
        engine.dispose()
