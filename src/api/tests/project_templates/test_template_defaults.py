import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import ProjectTemplate
from langboard_shared.domain.services.factory.ProjectTemplateService import ProjectTemplateService
from langboard_shared.helpers import InfraHelper


def test_defaults_validation_and_omission_preserve_existing_selection(monkeypatch):
    template = ProjectTemplate(name="Custom", columns=["Queue"], description="Existing", global_label_uids=["label"])
    repo = SimpleNamespace(project_template=Mock(), workflow_stage=Mock())
    repo.project_template.get_by_name.return_value = template
    monkeypatch.setattr(
        InfraHelper,
        "get_by_id_like",
        lambda model, uid: template if model is ProjectTemplate else (object() if uid == "label" else None),
    )
    service = ProjectTemplateService(None, None, repo)
    service.save_columns("Custom", [{"name": "Queue"}], "template")
    assert template.description == "Existing" and template.global_label_uids == ["label"]
    with pytest.raises(ValueError):
        service.save_columns(
            "Custom", [{"name": "Queue"}], "template", description="Changed", global_label_uids=["missing"]
        )
    assert template.description == "Existing"
    service.save_columns("Custom", [{"name": "Queue"}], "template", description="Changed", global_label_uids=[])
    assert template.description == "Changed" and template.global_label_uids == []


@pytest.mark.parametrize("result", [None, {"created": True}])
def test_project_creation_applies_existing_global_path_or_rolls_back(result, monkeypatch):
    template = ProjectTemplate(name="Custom", columns=["Queue"], global_label_uids=["label"])
    project = SimpleNamespace(id=1)
    column = SimpleNamespace(order=0)
    archive = SimpleNamespace(order=1)
    services = {
        "project": SimpleNamespace(create=Mock(return_value=project), delete=Mock()),
        "project_column": SimpleNamespace(create=Mock(return_value=column), dispatch_created=Mock()),
        "project_label": SimpleNamespace(use_global=Mock(return_value=result)),
    }
    repo = SimpleNamespace(
        project_column=SimpleNamespace(get_or_create_archive_if_not_exists=Mock(return_value=archive), update=Mock())
    )
    service = ProjectTemplateService(None, services.__getitem__, repo)
    service.get = Mock(return_value=template)
    service._apply_internal_bots = Mock()
    service._apply_scopes = Mock()
    service._apply_email_notification_policy = Mock()
    engine = sa.create_engine("sqlite://")
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    if result:
        service.create_project("user", "New")
    else:
        with pytest.raises(ValueError):
            service.create_project("user", "New")
    services["project_label"].use_global.assert_called_once_with("user", project, "label")
    services["project"].delete.assert_not_called()
    assert services["project_column"].dispatch_created.called is (result is not None)


def test_additive_migration_keeps_existing_templates():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261003100000-8c2ab63d914e.py"
    spec = importlib.util.spec_from_file_location("migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE project_template (id INTEGER PRIMARY KEY,name TEXT NOT NULL)"))
        connection.execute(sa.text("INSERT INTO project_template VALUES (1,'Legacy')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.execute(sa.text("SELECT name,description,global_label_uids FROM project_template")).one() == (
            "Legacy",
            "",
            "[]",
        )
        module.downgrade()
    engine.dispose()
