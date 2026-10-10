"""Checkitem projections batch real timer SQL and retain latest-record semantics."""

from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine, event
from ....core.db.DbEngine import DbEngine
from ....domain.models import CheckitemTimerRecord
from ....domain.models.Checkitem import CheckitemStatus
from ....infrastructure.repositories.factory.CheckitemTimerRecordRepository import CheckitemTimerRecordRepository
from .CheckitemService import CheckitemService


@pytest.mark.parametrize("view", ["checklist", "card", "active"])
def test_thousand_item_views_use_three_timer_queries_and_preserve_ties(monkeypatch, view):
    engine = create_engine("sqlite://")
    CheckitemTimerRecord.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    card = SimpleNamespace(id=2000, get_uid=lambda: "card", api_response=lambda: {"uid": "card"})
    project = SimpleNamespace(api_response=lambda: {"uid": "project"})
    checklist = SimpleNamespace(id=3000)
    items = [SimpleNamespace(id=i, checklist_id=3000, api_response=lambda i=i: {"uid": str(i)}) for i in range(1, 1001)]
    records = [(item, None, None) for item in items]
    active = [(item, card, project) for item in items]
    timers = CheckitemTimerRecordRepository(None, None)
    point_read = Mock(wraps=timers.get_by_checkitem_and_arc_type)
    timers.get_by_checkitem_and_arc_type = point_read
    rows = [CheckitemTimerRecord(id=i + 5000, checkitem_id=i, status=CheckitemStatus.Started) for i in range(1, 1000)]
    timestamp = datetime(2026, 10, 5, tzinfo=UTC)
    rows[0].created_at = timestamp
    # Same timestamp, greater ID is the authoritative newest event.
    rows.append(CheckitemTimerRecord(id=9000, checkitem_id=1, status=CheckitemStatus.Stopped, created_at=timestamp))
    with engine.begin() as conn:
        conn.execute(
            CheckitemTimerRecord.__table__.insert(),
            [{k: getattr(row, k) for k in CheckitemTimerRecord.model_fields} for row in rows],
        )
    queries = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: queries.append(statement),
    )
    service = CheckitemService(
        lambda _: None,
        lambda _: None,
        SimpleNamespace(
            checkitem=SimpleNamespace(
                get_all_by_checklist=Mock(return_value=records),
                get_all_by_card=Mock(return_value=records),
                get_started_work_by_user=Mock(return_value=active),
            ),
            checkitem_timer_record=timers,
        ),
    )
    infra = import_module(CheckitemService.__module__).InfraHelper
    monkeypatch.setattr(infra, "get_records_with_foreign_by_params", lambda *args: (card, checklist))
    monkeypatch.setattr(infra, "get_by_id_like", lambda *args: card)
    try:
        if view == "checklist":
            result = service.get_api_list_by_checklist(card, checklist)
        elif view == "card":
            result = service.get_api_map_by_card(card)[3000]
        else:
            result = [row["checkitem"] for row in service.get_active_work(SimpleNamespace())]
        assert len(result) == 1000
        assert "timer_started_at" not in result[0]
        assert "timer_started_at" in result[1]
        assert "timer_started_at" not in result[-1]
        timer_reads = [
            query
            for query in queries
            if query.lstrip().upper().startswith("SELECT") and "checkitem_timer_record" in query
        ]
        assert len(timer_reads) == 3
        point_read.assert_not_called()
        # Existing single-event callers resolve ties identically to the batch.
        assert point_read(1, "last").id == 9000
    finally:
        engine.dispose()
