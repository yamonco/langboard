"""Plans preview without persistence and roll all composed commands back on failure."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application.work_plan import WorkPlan, WorkPlanService
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    Card,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectColumn,
)
from sqlalchemy import create_engine, select, text


@pytest.mark.parametrize(
    "mode",
    ["commit", "item_failure", "conflict", "column_conflict", "type_conflict", "outer_rollback", "receipt_failure"],
)
@pytest.mark.parametrize("promote", [False, True])
def test_composed_plan_transaction(monkeypatch, mode, promote):
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text(f'CREATE TABLE "{Project.__tablename__}" (id INTEGER PRIMARY KEY)'))
        c.execute(text(f'INSERT INTO "{Project.__tablename__}" VALUES (1)'))
        c.execute(text(f'CREATE TABLE "{Card.__tablename__}" (id INTEGER PRIMARY KEY)'))
        c.execute(text(f'INSERT INTO "{Card.__tablename__}" VALUES (1)'))
        c.execute(text(f'CREATE TABLE "{Checklist.__tablename__}" (id INTEGER PRIMARY KEY, card_id INTEGER)'))
        c.execute(text(f'INSERT INTO "{Checklist.__tablename__}" VALUES (5, 1)'))
        c.execute(text(f'CREATE TABLE "{Checkitem.__tablename__}" (id INTEGER PRIMARY KEY, checklist_id INTEGER)'))
        c.execute(text(f'INSERT INTO "{Checkitem.__tablename__}" VALUES (6, 5)'))
        c.execute(text(f'CREATE TABLE "{ProjectColumn.__tablename__}" (id INTEGER PRIMARY KEY)'))
        c.execute(text(f'INSERT INTO "{ProjectColumn.__tablename__}" VALUES (3)'))
        c.execute(text(f'CREATE TABLE "{GlobalCardRelationshipType.__tablename__}" (id INTEGER PRIMARY KEY)'))
        c.execute(text(f'INSERT INTO "{GlobalCardRelationshipType.__tablename__}" VALUES (7)'))
        c.execute(text("CREATE TABLE created (kind TEXT)"))
        c.execute(text("CREATE TABLE receipts (key TEXT PRIMARY KEY, value TEXT)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    project = Project(id=1, owner_id=1, title="Board")
    anchor = Card(id=1, project_id=1, project_column_id=3, title="Anchor", order=0)
    child = Card(id=2, project_id=1, project_column_id=3, title="Child", order=1)
    checklist = Checklist(id=3, card_id=2, title="Steps")
    item = Checkitem(id=4, checklist_id=3, title="Verify")
    source_list = Checklist(id=5, card_id=1, title="Source")
    source_item = Checkitem(id=6, checklist_id=5, title="Child")
    column = ProjectColumn(id=3, project_id=1, name="Backlog", order=0)
    relationship_type = GlobalCardRelationshipType(id=7, parent_name="Contains", child_name="Part of")
    graph_event, list_event, item_event, cardify_event = Mock(), Mock(), Mock(), Mock()

    def write(kind):
        with DbSession.use(readonly=False) as db:
            db.exec(text("INSERT INTO created VALUES (:v)").bindparams(v=kind))

    def graph(*args):
        if promote:
            assert args[4][0][1] == child.get_uid()
        write("card-and-edge")
        with DbSession.use(readonly=False) as db:
            db.after_commit(graph_event)
        return {"created_cards": [] if promote else [child.api_response()]}

    def create_list(*_, **__):
        write("checklist")
        return checklist

    def create_item(*_, **__):
        write("item")
        return None if mode == "item_failure" else item

    def cardify(*_):
        write("cardification")
        source_item.cardified_id = child.id
        with DbSession.use(readonly=False) as db:
            db.after_commit(cardify_event)
        return True

    def read_receipt(_, __, key):
        with DbSession.use(readonly=True) as db:
            row = db.exec(
                select(text("value")).select_from(text("receipts")).where(text("key=:k").bindparams(k=key))
            ).first()
            return {"value": row[0]} if row else None

    def save_receipt(_, __, key, value):
        with DbSession.use(readonly=False) as db:
            db.exec(text("INSERT INTO receipts VALUES (:k,:v)").bindparams(k=key, v=value))
        return None if mode == "receipt_failure" else object()

    service = SimpleNamespace(
        metadata=SimpleNamespace(get_by_key_as_api=read_receipt, save=save_receipt),
        project=SimpleNamespace(get_by_id_like=lambda _: project),
        card=SimpleNamespace(get_by_id_like=lambda uid: anchor if uid == anchor.get_uid() else child),
        project_column=SimpleNamespace(get_by_id_like=lambda _: column),
        checklist=SimpleNamespace(
            get_api_list_by_card=lambda _: [],
            get_by_id_like=lambda _: source_list,
            create=create_list,
            dispatch_created=list_event,
        ),
        checkitem=SimpleNamespace(
            create=create_item, dispatch_created=item_event, get_by_id_like=lambda _: source_item, cardify=cardify
        ),
        card_relationship=SimpleNamespace(
            preview_graph_patch=Mock(return_value={}),
            apply_graph_patch=graph,
            repo=SimpleNamespace(
                card_relationship=SimpleNamespace(
                    get_graph_snapshot=lambda _: [],
                    get_global_relationship_types_map=lambda _: {7: relationship_type},
                )
            ),
        ),
    )
    plan = WorkPlan(
        project_uid=project.get_uid(),
        anchor_card_uid=anchor.get_uid(),
        new_cards=[{"client_ref": "new:child", "title": "Child"}],
        add_edges=[{"parent_ref": anchor.get_uid(), "child_ref": "new:child", "relationship_type_uid": "type"}],
        new_checklists=[{"target_card_ref": "new:child", "title": "Steps", "items": ["Verify"]}],
    )
    if promote:
        plan = WorkPlan(
            project_uid=project.get_uid(),
            anchor_card_uid=anchor.get_uid(),
            cardify_checkitems=[
                {
                    "client_ref": "cardify:child",
                    "source_card_uid": anchor.get_uid(),
                    "checkitem_uid": source_item.get_uid(),
                    "title": "Child",
                    "project_column_uid": column.get_uid(),
                }
            ],
            add_edges=[{"parent_ref": anchor.get_uid(), "child_ref": "cardify:child", "relationship_type_uid": "type"}],
            new_checklists=[{"target_card_ref": "cardify:child", "title": "Steps", "items": ["Verify"]}],
        )
    plans = WorkPlanService(SimpleNamespace(get_uid=lambda: "actor"), service)
    reviewed = plans.preview(plan)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM created")).scalar() == 0
    assert not any(cb.called for cb in (graph_event, list_event, item_event))
    if mode == "conflict":
        anchor.title = "Changed after preview"

    if mode == "column_conflict":
        column.name = "Changed after preview"
    if mode == "type_conflict":
        relationship_type.machine_semantic = "blocks_execution"

    def apply():
        with DbSession.atomic():
            result = plans.apply(plan, reviewed["revision"], "request-one")
            assert result["all_succeeded"] and len(result["checklists"]) == 1
            assert not any(cb.called for cb in (graph_event, list_event, item_event))
            if mode == "outer_rollback":
                raise RuntimeError("Outer plan failed")

    if mode == "commit":
        apply()
        assert plans.apply(plan, reviewed["revision"], "request-one")["replayed"]
        with pytest.raises(ValueError, match="reused"):
            plans.apply(plan.model_copy(update={"new_checklists": []}), reviewed["revision"], "request-one")
    else:
        with pytest.raises((ValueError, RuntimeError)):
            apply()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM created")).scalar() == (
            (4 if promote else 3) if mode == "commit" else 0
        )
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM receipts")).scalar() == int(mode == "commit")
    assert all(cb.call_count == int(mode == "commit") for cb in (graph_event, list_event, item_event))
    assert cardify_event.call_count == int(mode == "commit" and promote)
    engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"new_checklists": [{"target_card_ref": "new:missing", "title": "Tasks", "items": ["Verify"]}]},
        {"new_cards": [{"client_ref": "new:a", "title": "One"}, {"client_ref": "new:a", "title": "Two"}]},
        {"remove_relationship_uids": ["same", "same"]},
    ],
)
def test_plan_rejects_ambiguous_or_empty_payload(changes):
    with pytest.raises(ValueError):
        WorkPlan(project_uid="project", anchor_card_uid="anchor", **changes)
