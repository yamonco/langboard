"""Real registry readback drives batch state; edits never execute entry effects."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import ProjectColumn
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.infrastructure.repositories.factory.ProjectColumnRepository import ProjectColumnRepository
from langboard_shared.infrastructure.repositories.factory.WorkflowStageRepository import WorkflowStageRepository
from sqlalchemy import event, text
from src.api.tests.workflow_stages.test_registry import form


pytest_plugins = ["src.api.tests.workflow_stages.test_registry"]


def test_registry_edits_and_inactive_bindings_reinterpret_a_card_batch_without_effects(registry, monkeypatch):
    registry_service, engine = registry
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE project_column"))
    ProjectColumn.__table__.create(engine)
    column = ProjectColumn(project_id=1, name="User-defined name", workflow_stage="released")
    ProjectColumnRepository(None, None).insert(column)
    fields = form(
        counts_as_completed=True,
        active_queue_policy="exclude",
        overdue_policy="suppress",
        entry_effects=["complete_checkitems"],
    )
    definition = registry_service.save(fields)
    uid = definition.get_uid()
    cards = [
        SimpleNamespace(
            id=index,
            project_id=1,
            project_column_id=column.id,
            archived_at=None,
            is_linked_resource=False,
            last_change_seq=9,
            get_uid=lambda: "qa",
        )
        for index in range(1, 101)
    ]
    counts = Mock(return_value={index: (3, 1, 1, 0) for index in range(1, 101)})
    repo = SimpleNamespace(
        workflow_stage=WorkflowStageRepository(None, None),
        checkitem=SimpleNamespace(get_work_state_counts=counts),
        card_verification=SimpleNamespace(get_latest_by_card_ids=Mock(return_value={})),
    )
    monkeypatch.setattr(import_module(CardService.__module__), "dependency_blockers", lambda ids: {i: [] for i in ids})
    service = CardService(None, None, repo)
    queries = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cursor, statement, *_: queries.append(statement))
    states = service.get_work_states(cards)
    assert all(s["completed"] is True and s["verification_state"] == "partial" for s in states.values())
    assert all(s["active_queue_eligible"] is False and s["overdue_suppressed"] is True for s in states.values())
    assert len([q for q in queries if "FROM workflow_stage_definition" in q]) == 1
    # Policy edits alter interpretation immediately; inactive bindings still resolve.
    fields.update(counts_as_completed=False, active_queue_policy="conditional", overdue_policy="normal")
    registry_service.save(fields, uid)
    registry_service.deactivate(uid)
    states = service.get_work_states(cards)
    assert all(s["completed"] is False and s["overdue_suppressed"] is False for s in states.values())
    assert all(s["active_queue_eligible"] is None and s["execution_state"] == "human_active" for s in states.values())
    assert all(s["checklist_progress"] == {"total": 3, "completed": 1} for s in states.values())
    # Read projection creates neither checkitem mutations nor effect execution services.
    assert counts.call_count == 2
    with DbSession.use(readonly=True) as db:
        persisted = db.exec(SqlBuilder.select.table(ProjectColumn)).first()
    assert persisted.workflow_stage == "released"
