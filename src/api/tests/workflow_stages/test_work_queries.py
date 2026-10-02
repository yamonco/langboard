"""Native relational queries respect registry policies without display-name guesses."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    CardAssignedUser,
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
    for model in (User, Project, ProjectColumn, Card, CardAssignedUser, Checklist, Checkitem, WorkflowStageDefinition):
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
