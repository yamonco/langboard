"""Order, membership, unread cursor and notifications commit together."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import Card, Checkitem, Checklist, Project
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardPublisher, CheckitemPublisher, ChecklistPublisher
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("kind", ["checklist", "checkitem", "transfer"])
@pytest.mark.parametrize("mode", ["commit", "stamp_failure", "outer_rollback", "noop"])
def test_order_cursor_and_event_transaction(monkeypatch, kind, mode):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE state (position INTEGER, parent INTEGER, seq INTEGER)"))
        connection.execute(text("INSERT INTO state VALUES (0, 10, 7)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    project = Project(id=1, title="fixture")
    card = Card(id=2, project_id=1, project_column_id=3, title="fixture", last_change_seq=7)
    old = Checklist(id=10, card_id=2, title="first", order=0)
    new = Checklist(id=11, card_id=2, title="second", order=0)
    item = Checkitem(id=12, checklist_id=10, title="task", order=0)
    monkeypatch.setattr(InfraHelper, "get_records_with_foreign_by_params", lambda *args: (project, card, old))
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, uid: new if uid == "new" else old)
    monkeypatch.setattr(
        CheckitemService, "_CheckitemService__get_records_by_params", lambda *args: (project, card, item)
    )
    events = [Mock(), Mock(), Mock()]
    monkeypatch.setattr(ChecklistPublisher, "order_changed", events[0])
    monkeypatch.setattr(CheckitemPublisher, "order_changed", events[1])
    monkeypatch.setattr(CardPublisher, "metadata_changed", events[2])

    def update_order(row, parent, old_order, order, target=None):
        with DbSession.use(readonly=False) as db:
            db.exec(
                text("UPDATE state SET position=:position,parent=:parent").bindparams(
                    position=order, parent=target.id if target else 10
                )
            )
    def update_item(row):
        with DbSession.use(readonly=False) as db:
            db.exec(text("UPDATE state SET parent=:parent").bindparams(parent=row.checklist_id))

    def update_card(changed):
        with DbSession.use(readonly=False) as db:
            db.exec(text("UPDATE state SET seq=:seq").bindparams(seq=changed.last_change_seq))
        if mode == "stamp_failure":
            raise RuntimeError("stamp failed")

    repository = SimpleNamespace(
        card=SimpleNamespace(update=update_card),
        checklist=SimpleNamespace(update_column_order=update_order),
        checkitem=SimpleNamespace(update_row_order=update_order, update=update_item),
    )
    card_service = CardService(lambda _: None, lambda _: None, repository)
    monkeypatch.setattr(CardService, "next_change_seq", staticmethod(lambda: 8))
    cls = ChecklistService if kind == "checklist" else CheckitemService
    service = cls(lambda _: card_service, lambda _: card_service, repository)

    def invoke():
        if kind == "checklist":
            return service.change_order(project, card, old, 0 if mode == "noop" else 1)
        target = "new" if kind == "transfer" and mode != "noop" else ""
        return service.change_order(project, card, item, 0 if kind == "transfer" or mode == "noop" else 1, target)

    if mode == "stamp_failure":
        with pytest.raises(RuntimeError, match="stamp failed"):
            invoke()
    elif mode == "outer_rollback":
        with pytest.raises(RuntimeError, match="rollback"):
            with DbSession.atomic():
                assert invoke() is True
                assert not any(event.called for event in events)
                raise RuntimeError("rollback")
    else:
        assert invoke() is True
    with engine.connect() as connection:
        state = tuple(connection.execute(text("SELECT position,parent,seq FROM state")).one())
    if mode == "commit":
        assert state == (0 if kind == "transfer" else 1, 11 if kind == "transfer" else 10, 8)
        event = events[0] if kind == "checklist" else events[1]
        event.assert_called_once()
        events[2].assert_called_once()
        assert card.last_change_target_type == ("checklist" if kind == "checklist" else "checkitem")
    else:
        assert state == (0, 10, 7)
        assert not any(event.called for event in events)
