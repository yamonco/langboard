import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard.routes.settings.Form import SaveWorkflowStageForm  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.domain.models import WorkflowStageDefinition  # noqa: E402
from langboard_shared.domain.services.factory.WorkflowStageService import WorkflowStageService  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.WorkflowStageRepository import (
    WorkflowStageRepository,  # noqa: E402
)


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
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repo = WorkflowStageRepository(lambda _: None, lambda _: None)
    service = WorkflowStageService(lambda _: None, lambda _: None, SimpleNamespace(workflow_stage=repo))
    yield service, engine
    engine.dispose()


def form(**changes):
    return SaveWorkflowStageForm(key="released", name="Released", description="Accepted delivery", **changes).model_dump()


def test_create_update_deactivate_preserve_key_and_translations(registry):
    service, _ = registry
    fields = form(translations={"ko": {"name": "출시", "description": "인수 완료"}}, counts_as_completed=True, active_queue_policy="exclude", entry_effects=["stop_running_timers"])
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


@pytest.mark.parametrize("changes", [{"key":"renamed"}, {"entry_effects":["webhook"]}, {"active_queue_policy":"maybe"}, {"overdue_policy":"erase"}, {"is_builtin":True}, {"translations":{"../ko":{"name":"Bad"}}}])
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
        assert {row["key"] for row in rows} == {"backlog","ready","active","review","closed","reference"}
        for row in rows:
            assert set(row["translations"]) == {"en","ko","ja","zh"}
            assert row["entry_effects"] == []
            assert row["counts_as_completed"] == (row["key"] == "closed")
        assert next(row for row in rows if row["key"] == "closed")["overdue_policy"] == "suppress"
    engine.dispose()


def test_seed_retries_id_collisions_before_insert(monkeypatch):
    module = migration()
    identifiers = iter([1,1,2,2,3,4,5,6])
    monkeypatch.setattr(module, "SnowflakeID", lambda: next(identifiers))
    assert [row["id"] for row in module.builtin_rows()] == [1,2,3,4,5,6]
    monkeypatch.setattr(module, "SnowflakeID", lambda: 1)
    with pytest.raises(RuntimeError):
        module.builtin_rows()


def test_registry_routes_require_specific_admin_role():
    from langboard.routes.settings import WorkflowStageSettingsApi as api
    from langboard_shared.core.filter import AuthFilter
    from langboard_shared.filter import RoleFilter
    for endpoint, action in [(api.get_workflow_stages,"workflow_stage_read"),(api.create_workflow_stage,"workflow_stage_create"),(api.update_workflow_stage,"workflow_stage_update"),(api.deactivate_workflow_stage,"workflow_stage_deactivate")]:
        assert AuthFilter.get_filtered(endpoint) == "admin"
        _, actions, _, admin_bypass = RoleFilter.get_filtered(endpoint)
        assert actions == [action] and admin_bypass is False
