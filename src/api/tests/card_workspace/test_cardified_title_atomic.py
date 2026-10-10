"""Cardified title changes commit together and publish frozen state after commit."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CheckitemPublisher
from langboard_shared.tasks.activities import CardCheckitemActivityTask
from langboard_shared.tasks.bots import CardCheckitemBotTask
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("mode", ["second_write_failure", "outer_rollback", "commit"])
def test_cardified_title_transaction_and_after_commit(monkeypatch, mode):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE title_state (kind TEXT PRIMARY KEY, title TEXT)"))
        connection.execute(text("INSERT INTO title_state VALUES ('card', 'old'), ('item', 'old')"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    item = SimpleNamespace(id=1, title="old", cardified_id=2)
    linked = SimpleNamespace(title="old")
    item.model_copy = lambda **_: SimpleNamespace(title=item.title, id=item.id)
    linked.model_copy = lambda **_: SimpleNamespace(title=linked.title)
    owner = object()
    monkeypatch.setattr(
        CheckitemService, "_CheckitemService__get_records_by_params", lambda *args: (object(), owner, item)
    )
    monkeypatch.setattr(InfraHelper, "get_by", lambda *args: linked)
    monkeypatch.setattr(CheckitemService, "_mark_card_changed_for_unread", lambda *args: None)
    published = []
    monkeypatch.setattr(
        CheckitemPublisher, "title_changed", lambda p, c, i, linked: published.append((i.title, linked.title))
    )
    activity = Mock()
    bot = Mock()
    monkeypatch.setattr(CardCheckitemActivityTask, "card_checkitem_title_changed", activity)
    monkeypatch.setattr(CardCheckitemBotTask, "card_checkitem_title_changed", bot)

    def persist(kind, model):
        with DbSession.use(readonly=False) as db:
            db.exec(
                text("UPDATE title_state SET title=:title WHERE kind=:kind").bindparams(title=model.title, kind=kind)
            )
            if kind == "item" and mode == "second_write_failure":
                raise RuntimeError("second write failed")

    service = CheckitemService(
        lambda _: None,
        lambda _: None,
        SimpleNamespace(
            card=SimpleNamespace(update=lambda m: persist("card", m)),
            checkitem=SimpleNamespace(update=lambda m: persist("item", m)),
        ),
    )

    def change():
        with DbSession.atomic():
            service.change_title(object(), "project", "owner", "item", "first")
            assert not published
            service.change_title(object(), "project", "owner", "item", "second")
            assert not published
            if mode == "outer_rollback":
                raise RuntimeError("outer rollback")

    if mode == "commit":
        change()
        assert published == [("first", "first"), ("second", "second")]
        assert activity.call_count == bot.call_count == 2
    else:
        with pytest.raises(RuntimeError):
            change()
        assert published == []
        activity.assert_not_called()
        bot.assert_not_called()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT title FROM title_state ORDER BY kind")).scalars().all()
            == ["second" if mode == "commit" else "old"] * 2
        )
    engine.dispose()
