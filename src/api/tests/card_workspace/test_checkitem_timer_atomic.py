"""Timer state, history and outgoing events commit together."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models.Checkitem import CheckitemStatus
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CheckitemPublisher
from langboard_shared.tasks.activities import CardCheckitemActivityTask
from langboard_shared.tasks.bots import CardCheckitemBotTask
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("mode", ["commit", "history_failure", "outer_rollback"])
def test_stop_timer_state_and_dispatch_are_atomic(monkeypatch, mode):
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE timer_state (seconds INTEGER, status TEXT)"))
        c.execute(text("INSERT INTO timer_state VALUES (2, 'started')"))
        c.execute(text("CREATE TABLE timer_history (status TEXT)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    now = datetime.now(timezone.utc)
    item = SimpleNamespace(id=1, cardified_id=None, status=CheckitemStatus.Started, user_id=9, accumulated_seconds=2)
    item.model_copy = lambda **_: SimpleNamespace(**{k: v for k, v in vars(item).items() if k != "model_copy"})
    monkeypatch.setattr(
        CheckitemService, "_CheckitemService__get_records_by_params", lambda *a: (object(), object(), item)
    )
    monkeypatch.setattr(InfraHelper, "get_by", lambda *a: object())
    monkeypatch.setattr(CheckitemService, "_mark_card_changed_for_unread", lambda *a: None)
    callbacks = []
    for cls, name in (
        (CheckitemPublisher, "status_changed"),
        (CheckitemPublisher, "board_progress_changed"),
        (CardCheckitemActivityTask, "card_checkitem_timer_stopped"),
        (CardCheckitemBotTask, "card_checkitem_timer_stopped"),
    ):
        cb = Mock()
        monkeypatch.setattr(cls, name, cb)
        callbacks.append(cb)

    def update(m):
        with DbSession.use(readonly=False) as db:
            db.exec(
                text("UPDATE timer_state SET seconds=:s,status=:v").bindparams(
                    s=m.accumulated_seconds, v=m.status.value
                )
            )

    def history(record):
        with DbSession.use(readonly=False) as db:
            db.exec(text("INSERT INTO timer_history VALUES (:v)").bindparams(v=record.status.value))
            if mode == "history_failure":
                raise RuntimeError("history write failed")

    service = CheckitemService(
        lambda _: None,
        lambda _: None,
        SimpleNamespace(
            checkitem=SimpleNamespace(update=update),
            checkitem_timer_record=SimpleNamespace(
                get_by_checkitem_and_arc_type=lambda *a: SimpleNamespace(created_at=now - timedelta(seconds=5)),
                insert=history,
            ),
        ),
    )

    def stop():
        with DbSession.atomic():
            assert service.change_status(object(), "project", "card", "item", CheckitemStatus.Stopped, now)
            assert not any(cb.called for cb in callbacks)
            if mode == "outer_rollback":
                raise RuntimeError("plan failed")

    if mode == "commit":
        stop()
    else:
        with pytest.raises(RuntimeError):
            stop()
    with engine.connect() as c:
        assert c.execute(text("SELECT seconds,status FROM timer_state")).one() == (
            (7, "stopped") if mode == "commit" else (2, "started")
        )
        assert c.execute(text("SELECT count(*) FROM timer_history")).scalar() == int(mode == "commit")
    assert all(cb.call_count == int(mode == "commit") for cb in callbacks)
    engine.dispose()
