"""Native card create/update paths, additive global snapshots and SQL failure recovery."""

import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain import models
from langboard_shared.domain.contracts.title_labels import global_label_names
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibility
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardPublisher
from langboard_shared.tasks.activities import CardActivityTask
from langboard_shared.tasks.bots import CardBotTask
from sqlalchemy import create_engine, text


@pytest.fixture(params=["sqlite", "postgresql"])
def title_board(request, monkeypatch):
    admin = None
    schema = None
    if request.param == "postgresql":
        url = os.getenv("LANGBOARD_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL proof URL not set")
        admin = create_engine(url)
        schema = "title_labels_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine("sqlite://")
    required = {
        model.__table__
        for model in [
            models.User,
            models.Project,
            models.ProjectColumn,
            models.Card,
            models.GlobalLabel,
            models.ProjectLabel,
            models.CardAssignedProjectLabel,
            models.Checkitem,
        ]
    }
    pending = list(required)
    while pending:
        for fk in pending.pop().foreign_keys:
            if fk.column.table not in required:
                required.add(fk.column.table)
                pending.append(fk.column.table)
    models.Project.metadata.create_all(engine, tables=list(required))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    service = DomainService()
    effects = []
    monkeypatch.setattr(service.project_label, "dispatch_created", lambda *args: effects.append("snapshot"))
    monkeypatch.setattr(CardPublisher, "labels_updated", lambda *args: effects.append("assigned"))
    monkeypatch.setattr(CardPublisher, "updated", lambda *args: effects.append("updated"))
    monkeypatch.setattr(CardActivityTask, "card_updated", lambda *args: effects.append("activity"))
    monkeypatch.setattr(CardBotTask, "card_updated", lambda *args: effects.append("bot"))
    monkeypatch.setattr(service.card, "sync_completion_checkitem_title", lambda *args: None)
    monkeypatch.setattr(service.card, "next_change_seq", lambda: 1)
    monkeypatch.setattr(service.card, "default_creation_visibility", lambda *args: CardVisibility.Internal)
    monkeypatch.setattr(service.card, "_card_creator_projection", lambda *args: None)

    @contextmanager
    def execution():
        with DbSession.atomic():
            yield SimpleNamespace(watch_new=lambda *args: None)

    import importlib

    monkeypatch.setattr(importlib.import_module(service.card.__module__), "execution_readiness_uow", execution)
    try:
        with DbSession.atomic() as db:
            actor = models.User(firstname="Test", lastname="Owner", email="title@example.invalid", password="fixture")
            db.insert(actor)
            project = models.Project(owner_id=actor.id, title="Native title labels")
            db.insert(project)
            column = models.ProjectColumn(project_id=project.id, name="Queue", order=0)
            db.insert(column)
            bug = models.GlobalLabel(name="Bug", color="#123456", translations={"ko": {"name": "버그"}})
            question = models.GlobalLabel(name="Question", color="#654321")
            db.insert(bug)
            db.insert(question)
            local = models.ProjectLabel(
                project_id=project.id, name="Bug", color="#ABCDEF", description="Local", order=0
            )
            db.insert(local)
        monkeypatch.setattr(
            service.global_label, "title_names", lambda: global_label_names(service.global_label.get_api_list())
        )
        yield service, actor, project, column, local, bug, question, effects, engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin.dispose()


def create(board, title):
    service, actor, project, column, *_ = board
    from langboard_shared.core.db import EditorContentModel

    return service.card.create(
        actor, project, column, title, EditorContentModel(content="Keep body"), dispatch_effects=False
    )


def test_create_and_update_share_conversion_and_preserve_local_assignments(title_board):
    service, actor, project, _, local, bug, question, effects, _ = title_board
    card, response = create(title_board, "[버그][Bug] [Unknown] Work")
    assert card.title == "[Unknown] Work"
    assert len(response["labels"]) == 1
    assert response["labels"][0]["global_label_uid"] == bug.get_uid()
    assert response["labels"][0]["uid"] != local.get_uid()
    service.card.update_labels(actor, project, card, [local, response["labels"][0]["uid"]], dispatch_effects=False)
    service.card.update(actor, project, card, {"title": "[Question][Bug] Updated"})
    stored = InfraHelper.get_by_id_like(models.Card, card.id)
    assert stored.title == "Updated"
    assigned = service.card.repo.project_label.get_all_by_card(card)
    assert len(assigned) == 3
    assert {label.global_label_id for label in assigned} == {None, bug.id, question.id}
    service.card.update(actor, project, card, {"title": "[Question][Bug] Updated"})
    assert len(service.card.repo.project_label.get_all_by_card(card)) == 3
    assert effects.count("snapshot") == 2


def test_conversion_sql_failure_rolls_back_labels_callbacks_and_keeps_card_write(title_board, monkeypatch):
    service, actor, project, _, local, _, question, effects, engine = title_board
    card, _ = create(title_board, "Original")
    service.card.update_labels(actor, project, card, [local], dispatch_effects=False)
    original = service.project_label.use_global

    def fail_after_snapshot(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2] == question.get_uid():
            with DbSession.atomic() as db:
                # Real statement failure poisons PostgreSQL without the savepoint.
                db.exec(text("INSERT INTO missing_title_label_fixture VALUES (1)"))
        return result

    monkeypatch.setattr(service.project_label, "use_global", fail_after_snapshot)
    service.card.update(actor, project, card, {"title": "[Bug][Question] Requested"})
    assert InfraHelper.get_by_id_like(models.Card, card.id).title == "[Bug][Question] Requested"
    assert [label.id for label in service.card.repo.project_label.get_all_by_card(card)] == [local.id]
    assert len(service.card.repo.project_label.get_all_by_project(project)) == 1
    assert effects == ["updated", "activity", "bot"]
    effects.clear()
    created, response = create(title_board, "[Bug][Question] New")
    assert InfraHelper.get_by_id_like(models.Card, created.id).title == "[Bug][Question] New"
    assert response["labels"] == []
    assert effects == []


def test_registry_failure_and_token_only_title_preserve_normal_writes(title_board, monkeypatch):
    service, *_ = title_board
    monkeypatch.setattr(service.global_label, "title_names", lambda: (_ for _ in ()).throw(RuntimeError("fixture")))
    card, response = create(title_board, "[Bug] Keep")
    assert card.title == "[Bug] Keep" and response["labels"] == []


def test_outer_card_failure_discards_conversion_and_notifications(title_board):
    service, actor, project, _, _, _, _, effects, _ = title_board
    card, _ = create(title_board, "Original")
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            service.card.update(actor, project, card, {"title": "[Bug] Changed"})
            raise RuntimeError("Outer transaction failed")
    assert InfraHelper.get_by_id_like(models.Card, card.id).title == "Original"
    assert service.card.repo.project_label.get_all_by_card(card) == []
    assert effects == []


def test_stale_cache_collision_does_not_remove_tokens(title_board, monkeypatch):
    service, actor, project, _, _, bug, question, effects, _ = title_board
    old = global_label_names(service.global_label.get_api_list())
    monkeypatch.setattr(service.global_label, "title_names", lambda: old)
    question.translations = {"ko": {"name": "버그"}}
    with DbSession.atomic() as db:
        db.update(question)
    card, response = create(title_board, "[버그] Keep ambiguous")
    assert card.title == "[버그] Keep ambiguous"
    assert response["labels"] == [] and effects == []


def test_global_registry_cache_reused_and_invalidated_after_commit(monkeypatch):
    from unittest.mock import Mock
    from langboard_shared.core.caching import Cache
    from langboard_shared.domain.services.factory.GlobalLabelService import GlobalLabelService

    cache = {}
    monkeypatch.setattr(Cache, "get", lambda key: cache.get(key))
    monkeypatch.setattr(Cache, "set", lambda key, value, ttl: cache.update({key: value}))
    monkeypatch.setattr(Cache, "delete", lambda key: cache.pop(key, None))
    service = GlobalLabelService(None, None, SimpleNamespace(global_label=Mock()))
    read = Mock(return_value=[{"uid": "bug", "name": "Bug"}])
    monkeypatch.setattr(service, "get_api_list", read)
    assert service.title_names() == service.title_names() == {"Bug": "bug"}
    assert read.call_count == 1
    monkeypatch.setattr(InfraHelper, "get_by", lambda *args: None)
    service.save("Question", "#123456", "New definition")
    assert cache == {}
    service.title_names()
    assert read.call_count == 2


def test_registry_cache_invalidation_follows_outer_commit(title_board, monkeypatch):
    from langboard_shared.core.caching import Cache
    from langboard_shared.domain.services.factory.GlobalLabelService import GlobalLabelService

    service, *rest = title_board
    cache = {GlobalLabelService.TITLE_NAMES_CACHE: {"Old": "cached"}}
    monkeypatch.setattr(Cache, "delete", lambda key: cache.pop(key, None))
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            service.global_label.save("Rollback", "#123456", "Transient")
            assert cache
            raise RuntimeError("Rollback registry")
    assert cache
    assert InfraHelper.get_by(models.GlobalLabel, "name", "Rollback") is None
    with DbSession.atomic():
        service.global_label.save("Commit", "#123456", "Permanent")
        assert cache
    assert cache == {}
