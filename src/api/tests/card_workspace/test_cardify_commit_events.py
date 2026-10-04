"""Cardification dispatches only committed state, including outer plan rollback."""

import importlib
from contextlib import contextmanager
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
from langboard_shared.tasks.bots import CardBotTask, CardCheckitemBotTask
from sqlalchemy import create_engine, text


module = importlib.import_module("langboard_shared.domain.services.factory.CheckitemService")


@pytest.mark.parametrize("mode", ["commit", "outer_rollback", "link_failure", "foreign_column"])
def test_cardify_dispatch_is_commit_bound(monkeypatch, mode):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE cardify_state (kind TEXT PRIMARY KEY, value INTEGER)"))
        connection.execute(text("INSERT INTO cardify_state VALUES ('card', 0), ('item', 0)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    item = SimpleNamespace(id=1, title="Task", cardified_id=None, status=CheckitemStatus.Stopped)
    item.model_copy = lambda **_: SimpleNamespace(id=item.id, title=item.title, cardified_id=item.cardified_id)
    owner = SimpleNamespace(id=9, project_id=4, project_column_id=2, archived_at=None)
    target = SimpleNamespace(id=2, project_id=5 if mode == "foreign_column" else 4, is_archive=False)
    monkeypatch.setattr(
        CheckitemService, "_CheckitemService__get_records_by_params", lambda *args: (object(), owner, item)
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda *args: target)
    published = []
    monkeypatch.setattr(
        CheckitemPublisher, "cardified", lambda c, i, col, api: published.append((i.cardified_id, api["uid"]))
    )
    mocks = []
    for cls, name in (
        (CardCheckitemActivityTask, "card_checkitem_cardified"),
        (CardCheckitemBotTask, "card_checkitem_cardified"),
        (CardBotTask, "card_created"),
    ):
        callback = Mock()
        monkeypatch.setattr(cls, name, callback)
        mocks.append(callback)

    @contextmanager
    def readiness():
        with DbSession.atomic() as db:
            yield SimpleNamespace(db=db, watch_new=lambda _: None)

    monkeypatch.setattr(module, "execution_readiness_uow", readiness)

    def persist(kind, value):
        with DbSession.use(readonly=False) as db:
            db.exec(text("UPDATE cardify_state SET value=:value WHERE kind=:kind").bindparams(value=value, kind=kind))
            if kind == "item" and mode == "link_failure":
                raise RuntimeError("link write failed")

    def insert(card):
        card.id = 100
        persist("card", card.id)

    service = CheckitemService(
        lambda _: None,
        lambda _: SimpleNamespace(ensure_completion_checklist=lambda _: None),
        SimpleNamespace(
            card=SimpleNamespace(insert=insert, get_next_order=lambda *a, **k: 0),
            checkitem=SimpleNamespace(update=lambda m: persist("item", m.cardified_id)),
        ),
    )

    def apply():
        with DbSession.atomic():
            result = service.cardify(object(), "project", "card", "item", "column")
            assert not published
            if mode == "foreign_column":
                assert result is False
            else:
                assert result is True
            if mode == "outer_rollback":
                raise RuntimeError("plan failed")

    if mode in {"outer_rollback", "link_failure"}:
        with pytest.raises(RuntimeError):
            apply()
    else:
        apply()
    with engine.connect() as connection:
        values = connection.execute(text("SELECT value FROM cardify_state ORDER BY kind")).scalars().all()
    if mode == "commit":
        assert values == [100, 100]
        assert len(published) == 1
        assert all(mock.call_count == 1 for mock in mocks)
    else:
        assert values == [0, 0]
        assert not published
        assert all(mock.call_count == 0 for mock in mocks)
    engine.dispose()
