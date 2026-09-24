import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID
import pytest
from sqlalchemy import create_engine, text


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.tasks.webhooks import ExecutionOutboxWorker as worker  # noqa: E402


def test_nested_writes_commit_and_rollback_as_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE atomic_test (value integer)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    after_commit: list[str] = []
    with DbSession.atomic() as outer:
        outer.after_commit(lambda: after_commit.append("committed"))
        with DbSession.use(readonly=False) as nested:
            assert nested is outer
            nested.exec(text("INSERT INTO atomic_test VALUES (1)"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM atomic_test")).scalar() == 1
    assert after_commit == ["committed"]
    with pytest.raises(ValueError):
        with DbSession.atomic() as db:
            db.after_commit(lambda: after_commit.append("rolled-back"))
            with DbSession.use(readonly=False) as nested:
                nested.exec(text("INSERT INTO atomic_test VALUES (2)"))
            raise ValueError("rollback")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM atomic_test")).scalar() == 1
    assert after_commit == ["committed"]

    def failed_enqueue() -> None:
        raise RuntimeError("broker unavailable")

    with DbSession.atomic() as db:
        db.exec(text("INSERT INTO atomic_test VALUES (3)"))
        db.after_commit(failed_enqueue)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM atomic_test ORDER BY value")).scalars().all() == [1, 3]


def test_committed_outbox_row_is_published_once_per_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id = UUID("11111111-1111-4111-8111-111111111111")
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    responses = [
        (
            event_id,
            1,
            2,
            3,
            occurred_at,
            "io.langboard.work.ready.v1",
            {
                "title": "Task",
                "labels": ["backend"],
                "assignee_ids": [],
                "source_revision": "2026-09-24T00:00:00+00:00",
                "binding_id": "8",
                "binding_revision": occurred_at.isoformat(),
                "webhook_uid": "hook-40",
            },
        ),
    ]

    class FakeDb:
        def exec(self, statement):
            return SimpleNamespace(first=lambda: responses.pop(0))

    @contextmanager
    def fake_atomic():
        yield FakeDb()

    queued = []
    states = []
    monkeypatch.setattr(worker.DbSession, "atomic", fake_atomic)
    monkeypatch.setattr(
        worker, "binding_for_project", lambda uid: SimpleNamespace(id=8, updated_at=occurred_at, webhook_uid="hook-40")
    )
    monkeypatch.setattr(worker, "binding_invalid_reasons", lambda binding, event: [])
    monkeypatch.setattr(worker, "current_execution", lambda card_id, db: (occurred_at, True, 3))
    monkeypatch.setattr(worker, "webhook_delivery_task", lambda *args: queued.append(args))
    monkeypatch.setattr(worker, "_mark", lambda db, uid, state, error=None: states.append(state))

    assert worker.drain_one()
    assert len(queued) == 1
    assert queued[0][0].event_id == str(event_id)
    assert queued[0][0].data["execution_generation"] == 3
    assert queued[0][0].data["title"] == "Task"
    assert queued[0][0].data["labels"] == ["backend"]
    assert queued[0][1:] == ("hook-40", "8", occurred_at.isoformat())
    assert states == ["scheduled"]

    responses.append((event_id, 1, 2, 3, occurred_at, "io.langboard.work.ready.v1", {
        "title": "Task", "labels": [], "assignee_ids": [],
        "source_revision": occurred_at.isoformat(), "binding_id": "8",
        "binding_revision": occurred_at.isoformat(), "webhook_uid": "hook-40",
    }))
    monkeypatch.setattr(worker, "current_execution", lambda card_id, db: (occurred_at, False, 3))
    assert worker.drain_one()
    assert len(queued) == 1
    assert states == ["scheduled", "superseded"]
