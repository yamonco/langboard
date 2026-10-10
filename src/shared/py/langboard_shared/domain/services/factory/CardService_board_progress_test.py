"""Board progress reuses one authorized aggregate and preserves its wire fields."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
from sqlalchemy import create_engine, event
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibilityContext, CollaborationChannel
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ....domain.models import Checkitem, Checklist, ProjectColumn
from ....infrastructure.repositories.factory.CheckitemRepository import CheckitemRepository
from .CardService import CardService


def test_board_progress_and_work_state_share_one_scoped_aggregate(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (Checklist, Checkitem, ProjectColumn):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with engine.begin() as db:
        column = ProjectColumn(id=100, project_id=1, name="Fixture")
        db.execute(ProjectColumn.__table__.insert(), {k: getattr(column, k) for k in column.model_fields})
        lists = [Checklist(id=i + 1000, card_id=i, title="Work") for i in range(1, 101)]
        lists += [
            Checklist(id=2001, card_id=1, title="System", is_system=True),
            Checklist(id=2002, card_id=1, title="Deleted", deleted_at=SafeDateTime.now()),
            Checklist(id=2003, card_id=999, title="Outside visible batch"),
        ]
        db.execute(Checklist.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in lists])
        items = [
            Checkitem(id=i * 10 + j, checklist_id=i + 1000, title="Item", is_checked=j < 4)
            for i in range(1, 101)
            for j in range(10)
        ]
        items += [
            Checkitem(id=3001, checklist_id=2001, title="System", is_checked=True),
            Checkitem(id=3002, checklist_id=2002, title="Deleted list"),
            Checkitem(id=3003, checklist_id=1001, title="Deleted item", deleted_at=SafeDateTime.now()),
            Checkitem(id=3004, checklist_id=2003, title="Outside visible batch"),
        ]
        db.execute(Checkitem.__table__.insert(), [{k: getattr(row, k) for k in row.model_fields} for row in items])
    cards = [
        SimpleNamespace(
            id=i,
            project_id=1,
            visibility="PRIVATE" if i in (2, 3) else "SHARED",
            owner_user_id=7 if i in (2, 3) else None,
            project_column_id=100,
            archived_at=SafeDateTime.now() if i == 2 else None,
            deadline_at=None,
            description=SimpleNamespace(content="Body"),
            is_linked_resource=i == 3,
            last_change_seq=0,
            created_by_user_id=None,
            created_by_bot_id=None,
            get_uid=lambda i=i: str(i),
            board_api_response=lambda **fields: fields,
        )
        for i in range(1, 101)
    ]
    project = SimpleNamespace(id=1, archive_visible_days=7)
    module = import_module(CardService.__module__)
    monkeypatch.setattr(module.InfraHelper, "get_by_id_like", lambda *args: project)
    for name in ("dependency_blockers", "execution_generations", "pending_card_approvals", "card_signal_projections"):
        monkeypatch.setattr(module, name, lambda ids, **kwargs: {})
    relations = [SimpleNamespace(card_id_parent=a, card_id_child=b) for a, b in ((1, 2), (2, 3), (1, 4), (1, 101))]
    monkeypatch.setattr(module.CardRelationshipService, "public_relationship", lambda rel, _: {"edge": (rel.card_id_parent, rel.card_id_child)})
    repository = SimpleNamespace(
        card=SimpleNamespace(
            get_board_list=lambda *args, **kwargs: [(card, 0) for card in cards], get_board_creators=lambda *args: {}
        ),
        card_assigned_user=SimpleNamespace(get_all_by_project=lambda *args: []),
        card_relationship=SimpleNamespace(get_all_by_project=lambda *args: [(rel, None) for rel in relations]),
        project_label=SimpleNamespace(get_all_card_labels_by_project=lambda *args: []),
        checklist=SimpleNamespace(get_all_by_project=lambda *args, **kwargs: lists),
        checkitem=CheckitemRepository(None, None),
        card_verification=SimpleNamespace(get_latest_by_card_ids=lambda ids, **kwargs: {}),
        workflow_stage=SimpleNamespace(get_by_keys=lambda keys: {}),
    )
    service = CardService(lambda _: None, lambda _: None, repository)
    service.resolve_visibility_context = Mock(return_value=(project, CardVisibilityContext(CollaborationChannel.HumanUI, True, True, True, actor_user_id=7)))
    service.get_active_workers = Mock(return_value={})
    service._get_linked_resource_payloads = Mock(return_value={"3": {"fixture": True}})
    queries = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: queries.append(statement))
    try:
        result = service.get_board_list(project)
        aggregates = [query for query in queries if "count(checkitem.id)" in query]
        assert len(aggregates) == 1, aggregates
        assert len(result) == 100
        assert result[0]["relationships"] == [{"edge": (1, 4)}]
        assert result[1]["relationships"] == result[2]["relationships"] == [{"edge": (2, 3)}]
        for row in result:
            assert row["checklist_total_count"] == row["work_state"]["checklist_progress"]["total"] == 10
            assert row["checklist_completed_count"] == row["work_state"]["checklist_progress"]["completed"] == 4
        assert result[1]["work_state"]["lifecycle"] == "archived"
        assert result[2]["work_state"]["material_kind"] == "wiki-like"
        assert result[2]["linked_resource"] == {"fixture": True}
    finally:
        engine.dispose()
