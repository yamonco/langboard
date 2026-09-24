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
from langboard_shared.tasks.webhooks.ExecutionReadinessUow import CurrentExecution  # noqa: E402


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


def _drain_harness(monkeypatch: pytest.MonkeyPatch, snapshot: dict, current: CurrentExecution):
    """Run one drain with a faked row and point-read; return queued tasks and states."""
    event_id = UUID("11111111-1111-4111-8111-111111111111")
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    row = (
        event_id,
        1,
        2,
        current.generation,
        occurred_at,
        "io.langboard.work.ready.v1",
        snapshot,
    )

    class FakeDb:
        def exec(self, statement):
            return SimpleNamespace(first=lambda: row)

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
    monkeypatch.setattr(worker, "current_execution", lambda card_id, db: current)
    monkeypatch.setattr(worker, "webhook_delivery_task", lambda *args: queued.append(args))
    monkeypatch.setattr(worker, "_mark", lambda db, uid, state, error=None: states.append((state, error)))
    return event_id, occurred_at, queued, states


def _frozen_snapshot(occurred_at: datetime) -> dict:
    return {
        "title": "Frozen title",
        "labels": ["frozen-role"],
        "assignee_ids": [],
        "source_revision": "2026-09-24T00:00:00+00:00",
        "binding_id": "8",
        "binding_revision": occurred_at.isoformat(),
        "webhook_uid": "hook-40",
    }


def test_ready_content_edit_still_executes_once_with_latest_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """READY-preserving title edit: the event survives and delivers the latest content."""
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    edited_at = datetime(2026, 9, 24, 1, tzinfo=timezone.utc)
    current = CurrentExecution(
        revision=edited_at,
        is_ready=True,
        generation=5,
        title="Edited title",
        labels=["frozen-role"],
        assignee_ids=[7],
    )
    event_id, _, queued, states = _drain_harness(monkeypatch, _frozen_snapshot(occurred_at), current)

    assert worker.drain_one()
    assert len(queued) == 1
    data = queued[0][0].data
    assert data["execution_generation"] == 5
    assert data["title"] == "Edited title"
    assert data["source_revision"] == edited_at.isoformat()
    assert states == [("scheduled", None)]


def test_ready_role_label_change_delivers_latest_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """READY-preserving label change: delivered labels come from the point-read, never the frozen snapshot."""
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    current = CurrentExecution(
        revision=datetime(2026, 9, 24, 2, tzinfo=timezone.utc),
        is_ready=True,
        generation=5,
        title="Frozen title",
        labels=["reviewer"],
        assignee_ids=[],
    )
    _, _, queued, states = _drain_harness(monkeypatch, _frozen_snapshot(occurred_at), current)

    assert worker.drain_one()
    assert queued[0][0].data["labels"] == ["reviewer"]
    assert states == [("scheduled", None)]


def test_ready_to_blocked_supersedes_pending_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prerequisite added while pending: readiness is lost, the old generation executes zero times."""
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    current = CurrentExecution(
        revision=occurred_at,
        is_ready=False,
        generation=5,
        title="Frozen title",
        labels=[],
        assignee_ids=[],
    )
    _, _, queued, states = _drain_harness(monkeypatch, _frozen_snapshot(occurred_at), current)

    assert worker.drain_one()
    assert queued == []
    assert states == [("superseded", "stale_readiness")]


def test_blocked_to_ready_new_generation_supersedes_old_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """blocked→ready emits generation 6; the stale generation 5 event must not execute."""
    occurred_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    current = CurrentExecution(
        revision=occurred_at,
        is_ready=True,
        generation=6,
        title="Frozen title",
        labels=[],
        assignee_ids=[],
    )
    row_generation = 5
    event_id, _, queued, states = _drain_harness(monkeypatch, _frozen_snapshot(occurred_at), current)
    # The faked row keeps generation 5 while the card already advanced to 6.
    worker_row = (
        event_id,
        1,
        2,
        row_generation,
        occurred_at,
        "io.langboard.work.ready.v1",
        _frozen_snapshot(occurred_at),
    )

    class FakeDb:
        def exec(self, statement):
            return SimpleNamespace(first=lambda: worker_row)

    @contextmanager
    def fake_atomic():
        yield FakeDb()

    monkeypatch.setattr(worker.DbSession, "atomic", fake_atomic)

    assert worker.drain_one()
    assert queued == []
    assert states == [("superseded", "stale_readiness")]
