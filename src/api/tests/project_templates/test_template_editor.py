from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.models import ProjectTemplate
from langboard_shared.domain.services.factory.ProjectTemplateService import ProjectTemplateService
from langboard_shared.helpers import InfraHelper


def service(monkeypatch, template=None):
    repo = SimpleNamespace(project_template=Mock(), workflow_stage=Mock())
    repo.project_template.get_by_name.return_value = template
    repo.workflow_stage.get_by_keys.return_value = {"active": SimpleNamespace(is_active=True)}
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, uid: template)
    return ProjectTemplateService(None, None, repo), repo


def test_editor_preserves_automation_and_canonical_column_json(monkeypatch):
    template = ProjectTemplate(
        name="Custom",
        columns=["Queue"],
        column_descriptions=["Legacy"],
        internal_bots=[{"bot_type": "manager"}],
        column_bot_scopes=[{"column_name": "Queue", "bot_uname": "worker"}],
    )
    editor, repo = service(monkeypatch, template)
    saved = editor.save_columns(
        "Custom",
        [
            {
                "name": "Queue",
                "description": "English guidance",
                "workflow_stage": "active",
                "translations": {"ko": {"name": "대기", "description": "안내"}},
            }
        ],
        "uid",
    )
    assert saved.columns[0]["translations"]["en"] == {"name": "Queue", "description": "English guidance"}
    assert saved.columns[0]["workflow_stage"] == "active"
    assert saved.column_descriptions == []
    assert saved.internal_bots == [{"bot_type": "manager"}]
    assert saved.column_bot_scopes[0]["bot_uname"] == "worker"
    repo.project_template.update.assert_called_once()


@pytest.mark.parametrize(
    "column",
    [
        {"name": "Queue", "workflow_stage": "missing"},
        {"name": "Queue", "translations": {"bad_code": {"name": "x"}}},
        {"name": "Renamed"},
    ],
)
def test_invalid_structure_never_mutates_existing_snapshot(monkeypatch, column):
    template = ProjectTemplate(name="Custom", columns=["Queue"], column_bot_scopes=[{"column_name": "Queue"}])
    editor, repo = service(monkeypatch, template)
    with pytest.raises(ValueError):
        editor.save_columns("Custom", [column], "uid")
    assert template.columns == ["Queue"]
    repo.project_template.update.assert_not_called()
