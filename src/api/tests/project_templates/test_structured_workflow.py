"""Template workflow persistence and native column creation acceptance."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import Project, ProjectColumn, ProjectTemplate
from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
from langboard_shared.domain.services.factory.ProjectTemplateService import (
    SI_COLUMN_DESCRIPTIONS,
    SI_WORKFLOW_STAGES,
    ProjectTemplateService,
)
from langboard_shared.helpers import InfraHelper
from langboard_shared.infrastructure.repositories.factory.ProjectColumnRepository import ProjectColumnRepository
from langboard_shared.infrastructure.repositories.factory.ProjectTemplateRepository import ProjectTemplateRepository
from sqlalchemy import create_engine


@pytest.fixture
def storage(monkeypatch):
    engine = create_engine("sqlite://")
    ProjectTemplate.__table__.create(engine)
    from langboard_shared.domain.models import WorkflowStageDefinition
    from langboard_shared.infrastructure.repositories.factory.WorkflowStageRepository import WorkflowStageRepository
    WorkflowStageDefinition.__table__.create(engine)
    ProjectColumn.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repositories = SimpleNamespace(
        project_template=ProjectTemplateRepository(None, None),
        project_column=ProjectColumnRepository(None, None),
        workflow_stage=WorkflowStageRepository(None, None),
    )
    for key in SI_WORKFLOW_STAGES:
        repositories.workflow_stage.insert(WorkflowStageDefinition(key=key, name=key))
    yield repositories
    engine.dispose()


def test_structured_json_roundtrip_retains_duplicate_names_and_stage_keys(storage):
    template = ProjectTemplate(
        name="Support",
        columns=[
            {"name": "Queue", "description": "Awaiting work", "workflow_stage": "ready"},
            {"name": "Queue", "description": "Accepted work", "workflow_stage": "closed"},
        ],
    )
    storage.project_template.insert(template)
    loaded = storage.project_template.get_by_name("Support")
    assert loaded.column_definitions() == template.columns
    assert loaded.column_descriptions == []
    assert loaded.api_response()["columns"] == ["Queue", "Queue"]
    assert loaded.api_response()["column_descriptions"] == ["Awaiting work", "Accepted work"]
    assert set(loaded.columns[1]) == {"name", "description", "workflow_stage"}


def test_legacy_roundtrip_never_infers_done_meaning(storage):
    storage.project_template.insert(
        ProjectTemplate(name="Legacy", columns=["Done", "Done"], column_descriptions=["First", "Second"])
    )
    template = storage.project_template.get_by_name("Legacy")
    assert template.column_definitions() == [
        {"name": "Done", "description": "First", "workflow_stage": None},
        {"name": "Done", "description": "Second", "workflow_stage": None},
    ]


@pytest.mark.parametrize("invalid", [False, True])
def test_native_template_creation_persists_semantics_or_calls_project_cleanup(storage, monkeypatch, invalid):
    project = Project(id=1, owner_id=1, title="QA")
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, _uid: project)
    column_service = ProjectColumnService(None, None, storage)
    column_service.dispatch_created = Mock()
    project_service = SimpleNamespace(create=Mock(return_value=project), delete=Mock())
    services = {"project": project_service, "project_column": column_service}
    service = ProjectTemplateService(None, services.__getitem__, storage)
    service._apply_internal_bots = Mock()
    service._apply_scopes = Mock()
    service._apply_email_notification_policy = Mock()
    actor = object()
    if invalid:
        template = ProjectTemplate(
            name="Invalid",
            columns=[
                {"name": "Ready", "description": "Valid first", "workflow_stage": "ready"},
                {"name": "Unknown", "workflow_stage": "not_registered"},
            ],
        )
        storage.project_template.insert(template)
        with pytest.raises(ValueError, match="Unknown or inactive workflow stage"):
            service.create_project(actor, "QA", template_name="Invalid")
        project_service.delete.assert_called_once_with(actor, project)
        return
    _, columns, template = service.create_project(actor, "QA", template_name="SI")
    from langboard_shared.core.db import DbSession, SqlBuilder

    with DbSession.use(readonly=True) as db:
        loaded = db.exec(SqlBuilder.select.table(ProjectColumn).order_by(ProjectColumn.column("order"))).all()
    assert [column.workflow_stage for column in loaded if not column.is_archive] == SI_WORKFLOW_STAGES
    assert [column.description for column in loaded if not column.is_archive] == SI_COLUMN_DESCRIPTIONS
    assert sum(column.is_archive for column in loaded) == 1
    assert all(column.workflow_stage is None for column in loaded if column.is_archive)
    assert [column.name for column in columns] == template.api_response()["columns"]
    project_service.delete.assert_not_called()
    assert column_service.dispatch_created.call_count == 5
