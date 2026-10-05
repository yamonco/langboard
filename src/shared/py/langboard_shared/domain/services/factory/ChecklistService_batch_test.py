"""Bounded nested checklist reads use one item query and one timer batch."""

from datetime import UTC, datetime
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, event
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ....domain.models import Card, Checkitem, CheckitemTimerRecord, Checklist, User
from ....infrastructure.repositories.factory.CheckitemRepository import CheckitemRepository
from ....infrastructure.repositories.factory.CheckitemTimerRecordRepository import CheckitemTimerRecordRepository
from ....infrastructure.repositories.factory.ChecklistRepository import ChecklistRepository
from .CheckitemService import CheckitemService
from .ChecklistService import ChecklistService


@pytest.mark.parametrize("open_only", [False, True])
def test_hundred_lists_preserve_point_projection_with_five_queries(monkeypatch, open_only):
    engine = create_engine("sqlite://")
    for model in (Card, User, Checklist, Checkitem, CheckitemTimerRecord):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    actor = User(
        id=1,
        firstname="Fixture",
        lastname="Actor",
        username="fixture",
        email="fixture@example.invalid",
        password="fixture-only",
    )
    card = Card(id=2, project_id=1, project_column_id=1, created_by_user_id=1, title="Source")
    target = Card(id=3, project_id=1, project_column_id=1, created_by_user_id=1, title="Cardified")
    lists = [Checklist(id=i + 100, card_id=2, title=str(i), order=i) for i in range(100)]
    lists += [
        Checklist(id=500, card_id=2, title="System", is_system=True),
        Checklist(id=501, card_id=2, title="Deleted", deleted_at=SafeDateTime.now()),
        Checklist(id=502, card_id=99, title="Foreign"),
    ]
    items = [
        Checkitem(
            id=i * 20 + j + 1000,
            checklist_id=i + 100,
            title=str(j),
            order=0,
            is_checked=j < 3,
            cardified_id=3 if j == 3 else None,
            user_id=1 if j == 4 else None,
        )
        for i in range(100)
        for j in range(10)
    ]
    items += [
        Checkitem(id=3000 + i, checklist_id=list_id, title="Excluded") for i, list_id in enumerate([500, 501, 502])
    ]
    items += [Checkitem(id=999, checklist_id=100, title="Deleted", deleted_at=SafeDateTime.now())]
    timestamp = datetime(2026, 10, 5, tzinfo=UTC)
    timers = [
        CheckitemTimerRecord(id=4000, checkitem_id=1003, status="started", created_at=timestamp),
        CheckitemTimerRecord(id=4001, checkitem_id=1003, status="stopped", created_at=timestamp),
        CheckitemTimerRecord(id=4002, checkitem_id=1004, status="started", created_at=timestamp),
    ]
    with engine.begin() as db:
        for model, rows in [
            (User, [actor]),
            (Card, [card, target]),
            (Checklist, lists),
            (Checkitem, items),
            (CheckitemTimerRecord, timers),
        ]:
            db.execute(model.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in rows])
    repo = SimpleNamespace(
        checklist=ChecklistRepository(None, None),
        checkitem=CheckitemRepository(None, None),
        checkitem_timer_record=CheckitemTimerRecordRepository(None, None),
    )
    item_service = CheckitemService(lambda _: None, lambda _: None, repo)
    service = ChecklistService(lambda _: item_service, lambda _: None, repo)
    queries = []

    def listener(conn, cursor, statement, *args):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        result = service.get_api_list_by_card(card, limit=101, checkitems_limit=5, open_only=open_only)
        assert len([q for q in queries if q.lstrip().upper().startswith("SELECT")]) == 5, queries
        assert len(result) == 100
        assert all(len(row["checkitems"]) == 5 for row in result)
        expected_titles = [str(i) for i in range(3, 8)] if open_only else [str(i) for i in range(5)]
        assert [row["title"] for row in result[0]["checkitems"]] == expected_titles
        event.remove(engine, "before_cursor_execute", listener)
        expected = [
            {
                **cl.api_response(),
                "checkitems": item_service.get_api_list_by_checklist(card, cl, limit=5, open_only=open_only),
            }
            for cl in repo.checklist.get_all_by_card(card, limit=101, is_system=False, open_only=open_only)
        ]
        assert result == expected
        projected = {item["title"]: item for item in result[0]["checkitems"]}
        assert projected["3"]["cardified_card"]["uid"] == target.get_uid()
        assert "timer_started_at" not in projected["3"]
        assert projected["4"]["user"]["uid"] == actor.get_uid()
        assert projected["4"]["timer_started_at"] is not None
        # Valid sources retain all rows/timers and the unchanged projection.
        assert service.get_api_list_by_card(
            card, 101, 101, open_only=open_only, max_checklists=100, max_checkitems=100
        ) == service.get_api_list_by_card(card, 101, 101, open_only=open_only)
        # The repository enforces card ancestry even for a supplied foreign ID.
        assert repo.checkitem.get_all_by_checklists(card, [502], 5) == []
        assert repo.checkitem.get_all_by_checklists(card, [], 5) == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("open_only", [False, True])
def test_overbound_lists_reject_before_item_or_timer_hydration(monkeypatch, open_only):
    engine = create_engine("sqlite://")
    for model in (Card, Checklist, Checkitem):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    card = Card(id=2, project_id=1, project_column_id=1, created_by_user_id=1, title="Source")
    lists = [Checklist(id=i + 100, card_id=2, title=str(i), order=i) for i in range(101)]
    items = [Checkitem(id=i + 1000, checklist_id=i + 100, title="Open") for i in range(101)]
    with engine.begin() as db:
        for model, rows in [(Card, [card]), (Checklist, lists), (Checkitem, items)]:
            db.execute(model.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in rows])
    repo = SimpleNamespace(checklist=ChecklistRepository(lambda _: None, lambda _: None))

    def reject_hydration(_):
        raise AssertionError("Overbound source must not construct item service")

    service = ChecklistService(reject_hydration, lambda _: None, repo)
    queries = []

    def listener(conn, cursor, statement, *args):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        with pytest.raises(ValueError, match="safe 100-item MCP source bound"):
            service.get_api_list_by_card(card, limit=101, checkitems_limit=101, max_checklists=100, open_only=open_only)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(queries) == 1
    assert "checkitem_timer_record" not in queries[0]
    # Execute-mode membership is filtered by an EXISTS query, without hydrating items.
    assert ("checkitem" in queries[0]) is open_only


@pytest.mark.parametrize("maximum,limit", [(0, 1), (100, 100), (100, None)])
def test_source_bound_requires_sentinel_query(maximum, limit):
    service = ChecklistService(lambda _: None, lambda _: None, SimpleNamespace())
    with pytest.raises(ValueError, match="sentinel query limit"):
        service.get_api_list_by_card(None, limit=limit, max_checklists=maximum)


@pytest.mark.parametrize("view", ["single", "nested"])
@pytest.mark.parametrize("open_only", [False, True])
def test_overbound_checkitems_reject_before_timer_projection(monkeypatch, view, open_only):
    engine = create_engine("sqlite://")
    # Omit the timer table intentionally: any hydration query would fail.
    for model in (Card, User, Checklist, Checkitem):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    card = Card(id=2, project_id=1, project_column_id=1, created_by_user_id=1, title="Source")
    lists = [Checklist(id=100, card_id=2, title="Valid"), Checklist(id=101, card_id=2, title="Overbound")]
    items = [Checkitem(id=1000 + i, checklist_id=100, title="Valid", order=i) for i in range(100)]
    items += [Checkitem(id=2000 + i, checklist_id=101, title="Overbound", order=i) for i in range(101)]
    if open_only:
        items.append(Checkitem(id=3000, checklist_id=101, title="Checked", is_checked=True, order=-1))
    with engine.begin() as db:
        for model, rows in [(Card, [card]), (Checklist, lists), (Checkitem, items)]:
            db.execute(model.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in rows])
    repo = SimpleNamespace(
        checklist=ChecklistRepository(None, None),
        checkitem=CheckitemRepository(None, None),
        checkitem_timer_record=CheckitemTimerRecordRepository(None, None),
    )
    item_service = CheckitemService(lambda _: None, lambda _: None, repo)
    service = ChecklistService(lambda _: item_service, lambda _: None, repo)
    queries = []

    def listener(conn, cursor, statement, *args):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        with pytest.raises(ValueError, match="checkitems exceeds the safe 100-item MCP source bound"):
            if view == "single":
                item_service.get_api_list_by_checklist(card, lists[1], 101, open_only=open_only, max_checkitems=100)
            else:
                service.get_api_list_by_card(
                    card, 101, 101, open_only=open_only, max_checklists=100, max_checkitems=100
                )
        assert len(queries) == (1 if view == "single" else 2), queries
        assert not any("checkitem_timer_record" in query for query in queries)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        engine.dispose()


@pytest.mark.parametrize("maximum,limit", [(0, 1), (100, 100), (100, None)])
def test_checkitem_source_bound_requires_sentinel_query(maximum, limit):
    service = CheckitemService(lambda _: None, lambda _: None, SimpleNamespace())
    with pytest.raises(ValueError, match="sentinel query limit"):
        service.get_api_list_by_checklist(None, None, limit, max_checkitems=maximum)
    with pytest.raises(ValueError, match="sentinel query limit"):
        service.get_api_map_by_checklists(None, [], limit, max_checkitems=maximum)
