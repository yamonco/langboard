"""Unread metadata events never escape a rolled-back plan."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import Card
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.publishers import CardPublisher
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("rollback", [False, True])
def test_unread_metadata_dispatch_waits_for_outer_commit(monkeypatch, rollback):
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE changes (seq INTEGER)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    card = Card(id=1, project_id=2, project_column_id=3, title="Before commit", order=0)
    emitted = Mock()
    monkeypatch.setattr(CardPublisher, "metadata_changed", emitted)

    def update(c):
        with DbSession.use(readonly=False) as db:
            db.exec(text("INSERT INTO changes VALUES (:v)").bindparams(v=c.last_change_seq))

    service = CardService(lambda _: None, lambda _: None, SimpleNamespace(card=SimpleNamespace(update=update)))
    monkeypatch.setattr(service, "next_change_seq", lambda: 5)

    def run():
        with DbSession.atomic():
            service.mark_card_changed(card, "checkitem")
            assert not emitted.called
            card.title = "Changed after event registration"
            if rollback:
                raise RuntimeError("Plan failed")

    if rollback:
        with pytest.raises(RuntimeError):
            run()
    else:
        run()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM changes")).scalar() == int(not rollback)
    assert emitted.call_count == int(not rollback)
    if not rollback:
        assert emitted.call_args.args[0].title == "Before commit"
        assert emitted.call_args.args[0].last_change_seq == 5
    engine.dispose()
