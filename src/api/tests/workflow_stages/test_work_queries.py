"""Native relational queries respect registry policies without display-name guesses."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    CardAssignedUser,
    CardAttachment,
    CardComment,
    Checkitem,
    Checklist,
    Project,
    ProjectColumn,
    User,
    WorkflowStageDefinition,
)
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository
from langboard_shared.infrastructure.repositories.factory.ProjectColumnRepository import ProjectColumnRepository
from sqlalchemy import create_engine


@pytest.fixture
def work_db(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (
        User,
        Project,
        ProjectColumn,
        Card,
        CardAssignedUser,
        CardComment,
        CardAttachment,
        Checklist,
        Checkitem,
        WorkflowStageDefinition,
    ):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        user = User(firstname="QA", lastname="Policy", email="qa-query@example.invalid", password="fixture-only")
        db.insert(user)
        project = Project(owner_id=user.id, title="Scoped")
        foreign = Project(owner_id=user.id, title="Foreign")
        db.insert(project)
        db.insert(foreign)
        definitions = {}
        for key, complete, policy in [
            ("released", True, "exclude"),
            ("waiting", False, "exclude"),
            ("reference", False, "exclude"),
            ("active", False, "include"),
        ]:
            definition = WorkflowStageDefinition(
                key=key, name=key, counts_as_completed=complete, active_queue_policy=policy
            )
            db.insert(definition)
            definitions[key] = definition
        columns, cards = {}, {}
        for key, name in [
            ("released", "Still Doing"),
            ("waiting", "Wait"),
            ("reference", "Material"),
            ("active", "Done"),
            (None, "Completed"),
        ]:
            column = ProjectColumn(project_id=project.id, name=name, workflow_stage=key)
            db.insert(column)
            card = Card(project_id=project.id, project_column_id=column.id, title=name, created_by_user_id=user.id)
            db.insert(card)
            columns[key], cards[key] = column, card
        db.insert(
            Card(
                project_id=foreign.id,
                project_column_id=columns["active"].id,
                title="Foreign",
                created_by_user_id=user.id,
            )
        )
        db.insert(
            Card(
                project_id=project.id,
                project_column_id=columns["active"].id,
                title="Wiki",
                created_by_user_id=user.id,
                source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
                source_uid="fixture-wiki",
            )
        )
    yield SimpleNamespace(user=user, project=project, definitions=definitions, columns=columns, cards=cards)
    engine.dispose()


def my_work(data, purposes=None):
    now = SafeDateTime.now()
    return CardRepository(None, None).get_my_work_page(
        data.user, [data.project], purposes or {"created"}, [], now, now, "updated_at", None, None, 50
    )


def test_open_counts_keep_waiting_work_and_ignore_renamed_completion(work_db):
    data = work_db
    counts = ProjectColumnRepository(None, None).get_work_counts(data.project)
    assert counts[data.columns["released"].id]["open_count"] == 0
    assert counts[data.columns["waiting"].id]["open_count"] == 1  # Queue exclusion does not mean completion.
    assert counts[data.columns["reference"].id]["open_count"] == 0
    assert counts[data.columns["active"].id]["open_count"] == 1
    assert counts[data.columns[None].id]["open_count"] == 1  # Mutable name Completed supplies no policy.
    with DbSession.use(readonly=False) as db:
        stage = data.definitions["released"]
        stage.counts_as_completed = False
        stage.is_active = False  # Inactive existing bindings retain semantics.
        db.update(stage)
    assert (
        ProjectColumnRepository(None, None).get_work_counts(data.project)[data.columns["released"].id]["open_count"]
        == 1
    )


def test_my_work_uses_completed_and_queue_policy_before_pagination(work_db):
    data = work_db
    assert {card.id for card, *_ in my_work(data)} == {data.cards["active"].id, data.cards[None].id}
    with DbSession.use(readonly=False) as db:
        stage = data.definitions["waiting"]
        stage.active_queue_policy = "include"
        stage.is_active = False
        db.update(stage)
    assert {card.id for card, *_ in my_work(data)} == {
        data.cards["active"].id,
        data.cards[None].id,
        data.cards["waiting"].id,
    }


def test_overdue_purpose_excludes_suppressed_policy_without_hiding_other_work(work_db):
    data = work_db
    with DbSession.use(readonly=False) as db:
        card = data.cards["active"]
        card.deadline_at = SafeDateTime(2020, 1, 1)
        db.update(card)
        stage = data.definitions["active"]
        stage.overdue_policy = "suppress"
        db.update(stage)
    assert my_work(data, {"overdue"}) == []
    assert data.cards["active"].id in {card.id for card, *_ in my_work(data)}
    with DbSession.use(readonly=False) as db:
        stage.overdue_policy = "normal"
        db.update(stage)
    assert {card.id for card, *_ in my_work(data, {"overdue"})} == {data.cards["active"].id}


def test_project_page_and_search_filter_registry_completion_before_limit(work_db):
    data = work_db
    repo = CardRepository(None, None)
    page = repo.get_page_by_project(data.project, 25, include_closed=False)
    ids = {card.id for card, _ in page}
    assert data.cards["released"].id not in ids
    assert data.cards["active"].id in ids  # Display name Done is not completion.
    assert data.cards[None].id in ids
    assert repo.count_by_project(data.project, include_closed=False) == len(page)
    assert data.cards["released"].id in {
        card.id for card, _ in repo.get_page_by_project(data.project, 25, include_closed=True)
    }
    assert repo.get_page_by_project(data.project, 25, include_closed=False, workflow_stages=["released"]) == []
    assert {
        card.id
        for card, _ in repo.get_page_by_project(data.project, 25, include_closed=True, workflow_stages=["released"])
    } == {data.cards["released"].id}
    assert repo.count_by_project(data.project, include_closed=True, workflow_stages=["released"]) == 1
    assert repo.get_page_by_project(data.project, 25, workflow_stages=[]) == []
    assert repo.search_context_by_project(data.project, "Still", include_closed=False) == []
    assert {card.id for card, _ in repo.search_context_by_project(data.project, "Still", include_closed=True)} == {
        data.cards["released"].id
    }
    assert {
        card.id
        for card, _ in repo.search_context_by_project(
            data.project, "Done", include_closed=False, workflow_stages=["active"]
        )
    } == {data.cards["active"].id}
    with DbSession.use(readonly=False) as db:
        data.definitions["released"].counts_as_completed = False
        data.definitions["released"].is_active = False
        db.update(data.definitions["released"])
    assert data.cards["released"].id in {
        card.id for card, _ in repo.get_page_by_project(data.project, 25, include_closed=False)
    }


def test_open_acceptance_is_filtered_before_both_repository_limits(work_db):
    from langboard_shared.infrastructure.repositories.factory.CheckitemRepository import CheckitemRepository
    from langboard_shared.infrastructure.repositories.factory.ChecklistRepository import ChecklistRepository

    card = work_db.cards["active"]
    with DbSession.use(readonly=False) as db:
        closed = Checklist(card_id=card.id, title="Old completed acceptance", order=0)
        active = Checklist(card_id=card.id, title="Current acceptance", order=1)
        db.insert(closed)
        db.insert(active)
        db.insert(Checkitem(checklist_id=closed.id, title="Already done", is_checked=True))
        for i in range(105):
            db.insert(Checkitem(checklist_id=active.id, title=f"History {i}", is_checked=True, order=i))
        remaining = Checkitem(checklist_id=active.id, title="Only open item", order=105)
        db.insert(remaining)
    checklists = ChecklistRepository(None, None).get_all_by_card(card, limit=1, is_system=False, open_only=True)
    assert [item.id for item in checklists] == [active.id]
    items = CheckitemRepository(None, None).get_all_by_checklist(active, limit=1, open_only=True)
    assert [item.id for item, *_ in items] == [remaining.id]
    legacy = CheckitemRepository(None, None).get_all_by_checklist(active, limit=1)
    assert legacy[0][0].is_checked is True
