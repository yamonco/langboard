import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard.routes.settings.Form import SaveWorkflowStageForm  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.domain.models import WorkflowStageDefinition  # noqa: E402
from langboard_shared.domain.services.factory.WorkflowStageService import (
    WorkflowStageEditConflict,
    WorkflowStageService,  # noqa: E402
)
from langboard_shared.infrastructure.repositories.factory.WorkflowStageRepository import (
    WorkflowStageRepository,  # noqa: E402
)
from langboard_shared.publishers import AppSettingPublisher


def migration():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261002114000-4afb6de824d3.py"
    spec = importlib.util.spec_from_file_location("workflow_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry(monkeypatch):
    engine = create_engine("sqlite://")
    WorkflowStageDefinition.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE project_column (id BIGINT, workflow_stage TEXT, deleted_at TEXT, is_archive BOOLEAN)")
        )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE card(id BIGINT, project_column_id BIGINT)"))
        connection.execute(text("CREATE TABLE card_relationship(card_id_parent BIGINT, card_id_child BIGINT)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repo = WorkflowStageRepository(lambda _: None, lambda _: None)
    service = WorkflowStageService(lambda _: None, lambda _: None, SimpleNamespace(workflow_stage=repo))
    monkeypatch.setattr(service, "_publish_work_states", Mock())
    monkeypatch.setattr(AppSettingPublisher, "workflow_stages_changed", Mock())
    yield service, engine
    engine.dispose()


def form(**changes):
    return SaveWorkflowStageForm(
        key="released", name="Released", description="Accepted delivery", **changes
    ).model_dump()


def test_stale_editor_cannot_overwrite_or_deactivate_latest_stage(registry):
    service, _ = registry
    fields = form()
    stage = service.save(fields)
    uid = stage.get_uid()
    original = service.get_api_list()[0]["revision"]
    service.save({**fields, "name": "Latest", "expected_revision": original}, uid)
    latest = service.get_api_list()[0]
    assert latest["revision"] != original
    publisher = AppSettingPublisher.workflow_stages_changed
    publisher.reset_mock()
    with pytest.raises(WorkflowStageEditConflict):
        service.save({**fields, "name": "Stale", "expected_revision": original}, uid)
    with pytest.raises(WorkflowStageEditConflict):
        service.deactivate(uid, original)
    publisher.assert_not_called()
    service._publish_work_states.assert_not_called()
    saved = service.get_api_list()[0]
    assert saved["name"] == "Latest" and saved["is_active"] is True
    service.deactivate(uid, saved["revision"])
    inactive = service.get_api_list()[0]
    assert inactive["is_active"] is False and inactive["revision"] != saved["revision"]


def test_registry_invalidation_publishes_after_commit_only(registry):
    from langboard_shared.core.db import DbSession

    service, _ = registry
    publisher = AppSettingPublisher.workflow_stages_changed
    with DbSession.atomic():
        stage = service.save(form())
        publisher.assert_not_called()
    publisher.assert_called_once_with()
    publisher.reset_mock()
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            service.save({**form(), "name": "Rolled back"}, stage.get_uid())
            publisher.assert_not_called()
            raise RuntimeError("rollback")
    publisher.assert_not_called()
    with DbSession.atomic():
        service.save({**form(), "description": "Updated guidance"}, stage.get_uid())
        publisher.assert_not_called()
    publisher.assert_called_once_with()
    publisher.reset_mock()
    with DbSession.atomic():
        service.deactivate(stage.get_uid())
        publisher.assert_not_called()
    publisher.assert_called_once_with()


def test_create_update_deactivate_preserve_key_and_translations(registry):
    service, _ = registry
    fields = form(
        translations={"ko": {"name": "출시", "description": "인수 완료"}},
        counts_as_completed=True,
        active_queue_policy="exclude",
        entry_effects=["stop_running_timers"],
    )
    stage = service.save(fields)
    uid = stage.get_uid()
    saved = service.get_api_list()[0]
    assert saved["translations"]["en"]["name"] == "Released"
    assert saved["translations"]["ko"]["name"] == "출시"
    assert saved["entry_effects"] == ["stop_running_timers"]
    assert saved["counts_as_completed"] is True
    fields["name"] = "Delivered"
    service.save(fields, uid)
    assert service.get_api_list()[0]["name"] == "Delivered"
    service.deactivate(uid)
    saved = service.get_api_list()[0]
    assert saved["is_active"] is False and saved["key"] == "released"
    assert saved["translations"]["ko"]["name"] == "출시"


@pytest.mark.parametrize(
    "changes",
    [
        {"key": "renamed"},
        {"entry_effects": ["webhook"]},
        {"active_queue_policy": "maybe"},
        {"overdue_policy": "erase"},
        {"is_builtin": True},
        {"translations": {"../ko": {"name": "Bad"}}},
    ],
)
def test_invalid_update_has_no_write(registry, changes):
    service, _ = registry
    fields = form()
    stage = service.save(fields)
    with pytest.raises(ValueError):
        service.save({**fields, **changes}, stage.get_uid())
    saved = service.get_api_list()[0]
    assert saved["key"] == "released" and saved["is_builtin"] is False
    assert saved["entry_effects"] == []


def test_duplicate_and_missing_target_do_not_create(registry):
    service, _ = registry
    service.save(form())
    with pytest.raises(ValueError):
        service.save(form())
    assert service.save(form(), "missing") is None
    assert len(service.get_api_list()) == 1


def test_migration_installs_six_translated_policies_without_entry_effects():
    module = migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        rows = connection.execute(select(WorkflowStageDefinition.__table__)).mappings().all()
        assert len(rows) == 6
        assert {row["key"] for row in rows} == {"backlog", "ready", "active", "review", "closed", "reference"}
        for row in rows:
            assert set(row["translations"]) == {"en", "ko", "ja", "zh"}
            assert row["entry_effects"] == []
            assert row["counts_as_completed"] == (row["key"] == "closed")
        assert next(row for row in rows if row["key"] == "closed")["overdue_policy"] == "suppress"
    engine.dispose()


def test_seed_retries_id_collisions_before_insert(monkeypatch):
    module = migration()
    identifiers = iter([1, 1, 2, 2, 3, 4, 5, 6])
    monkeypatch.setattr(module, "SnowflakeID", lambda: next(identifiers))
    assert [row["id"] for row in module.builtin_rows()] == [1, 2, 3, 4, 5, 6]
    monkeypatch.setattr(module, "SnowflakeID", lambda: 1)
    with pytest.raises(RuntimeError):
        module.builtin_rows()


def test_registry_routes_require_specific_admin_role():
    from langboard.routes.settings import WorkflowStageSettingsApi as api
    from langboard_shared.core.filter import AuthFilter
    from langboard_shared.filter import RoleFilter

    for endpoint, action in [
        (api.get_workflow_stages, "workflow_stage_read"),
        (api.create_workflow_stage, "workflow_stage_create"),
        (api.update_workflow_stage, "workflow_stage_update"),
        (api.deactivate_workflow_stage, "workflow_stage_deactivate"),
    ]:
        assert AuthFilter.get_filtered(endpoint) == "admin"
        _, actions, _, admin_bypass = RoleFilter.get_filtered(endpoint)
        assert actions == [action] and admin_bypass is False


def test_column_usage_counts_explicit_non_deleted_non_archive_bindings(registry):
    service, engine = registry
    service.save(form())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_column VALUES (1, 'released', NULL, FALSE), (2, 'released', 'deleted', FALSE), (3, 'released', NULL, TRUE), (4, NULL, NULL, FALSE)"
            )
        )
    assert service.get_api_list()[0]["used_column_count"] == 1


def test_policy_update_publishes_after_commit_without_replaying_effects(registry):
    from langboard_shared.core.db import DbSession

    service, _ = registry
    fields = form(entry_effects=["complete_checkitems"])
    stage = service.save(fields)
    service._publish_work_states.assert_not_called()
    with DbSession.atomic():
        service.save({**fields, "overdue_policy": "suppress"}, stage.get_uid())
        service._publish_work_states.assert_not_called()
    service._publish_work_states.assert_called_once_with("released")
    service._publish_work_states.reset_mock()
    with pytest.raises(RuntimeError):
        with DbSession.atomic():
            service.save({**fields, "active_queue_policy": "exclude"}, stage.get_uid())
            raise RuntimeError("rollback")
    service._publish_work_states.assert_not_called()
    service.save({**fields, "name": "Renamed", "overdue_policy": "suppress"}, stage.get_uid())
    service._publish_work_states.assert_not_called()


def test_policy_projection_targets_bound_cards_and_same_project_dependents(registry):
    service, engine = registry
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE card"))
        connection.execute(
            text("CREATE TABLE card(id BIGINT, project_id BIGINT, project_column_id BIGINT, deleted_at TEXT)")
        )
        connection.execute(
            text("INSERT INTO project_column VALUES (1, 'released', NULL, FALSE), (2, 'active', NULL, FALSE)")
        )
        connection.execute(text("ALTER TABLE project_column ADD COLUMN project_id BIGINT DEFAULT 10"))
        connection.execute(
            text("INSERT INTO card VALUES (1,10,1,NULL),(2,10,2,NULL),(3,20,2,NULL),(4,10,1,'deleted'),(5,10,2,NULL)")
        )
        connection.execute(text("INSERT INTO card_relationship VALUES (1,2),(1,3),(1,2),(4,5)"))
    assert set(service.repo.workflow_stage.get_policy_affected_cards("released")) == {(10, 1), (10, 2)}
    assert service.repo.workflow_stage.get_policy_affected_cards("missing") == []
