from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.models import ProjectTemplate
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.services.factory.ProjectTemplateService import ProjectTemplateService
from langboard_shared.helpers import InfraHelper


def setup(monkeypatch):
    template = ProjectTemplate(
        name="Custom",
        columns=["Queue"],
        internal_bots=[
            {
                "internal_bot_uid": "old",
                "bot_type": "project_chat",
                "prompt": "Preserve instructions",
                "use_default_prompt": False,
            }
        ],
        project_bot_scopes=[{"bot_uname": "worker"}],
    )
    bots = {
        "old": SimpleNamespace(bot_type=InternalBotType.ProjectChat, get_uid=lambda: "old"),
        "new": SimpleNamespace(bot_type=InternalBotType.ProjectChat, get_uid=lambda: "new"),
        "editor": SimpleNamespace(bot_type=InternalBotType.EditorChat, get_uid=lambda: "editor"),
    }
    repo = SimpleNamespace(project_template=Mock())
    repo.project_template.get_by_name.return_value = template
    monkeypatch.setattr(
        InfraHelper, "get_by_id_like", lambda model, uid: template if model is ProjectTemplate else bots.get(uid)
    )
    return template, ProjectTemplateService(None, None, repo), repo


def test_selection_switch_preserves_prompt_and_scopes(monkeypatch):
    template, service, repo = setup(monkeypatch)
    service.save_columns("Custom", [{"name": "Queue"}], "template", internal_bot_uids=["new", "editor"])
    assert template.internal_bots == [
        {
            "internal_bot_uid": "new",
            "bot_type": "project_chat",
            "prompt": "Preserve instructions",
            "use_default_prompt": False,
        },
        {"internal_bot_uid": "editor", "bot_type": "editor_chat", "prompt": "", "use_default_prompt": True},
    ]
    assert template.project_bot_scopes == [{"bot_uname": "worker"}]
    repo.project_template.update.assert_called_once()
    response = template.api_response()
    assert response["internal_bot_selections"][0] == {"internal_bot_uid": "new", "bot_type": "project_chat"}
    assert "internal_bots" not in response
    assert "prompt" not in str(response)


@pytest.mark.parametrize("uids", [["missing"], ["old", "new"], ["old", "old"]])
def test_invalid_selection_does_not_mutate_template(monkeypatch, uids):
    template, service, repo = setup(monkeypatch)
    with pytest.raises(ValueError):
        service.save_columns("Custom", [{"name": "Changed"}], "template", internal_bot_uids=uids)
    assert template.columns == ["Queue"]
    assert template.internal_bots[0]["internal_bot_uid"] == "old"
    repo.project_template.update.assert_not_called()


def test_omission_preserves_snapshot_and_clear_restores_solution_defaults(monkeypatch):
    template, service, _ = setup(monkeypatch)
    service.save_columns("Custom", [{"name": "Queue"}], "template")
    assert template.internal_bots[0]["internal_bot_uid"] == "old"
    service.save_columns("Custom", [{"name": "Queue"}], "template", internal_bot_uids=[])
    assert template.internal_bots == []
    assert template.project_bot_scopes == [{"bot_uname": "worker"}]


def test_bot_choice_route_returns_only_public_selection_fields():
    import json
    from langboard.routes.settings.ProjectTemplateSettingsApi import get_project_template_bots
    from langboard_shared.core.filter import AuthFilter

    service = SimpleNamespace(
        internal_bot=SimpleNamespace(
            get_api_list=Mock(
                return_value=[
                    {
                        "uid": "bot",
                        "bot_type": "project_chat",
                        "display_name": "Assistant",
                        "api_key": "secret",
                        "api_url": "private",
                        "value": "instructions",
                    }
                ]
            )
        )
    )
    response = get_project_template_bots(service)
    assert json.loads(response.body) == {
        "bots": [{"uid": "bot", "bot_type": "project_chat", "display_name": "Assistant"}]
    }
    service.internal_bot.get_api_list.assert_called_once_with(is_setting=False)
    assert AuthFilter.get_filtered(get_project_template_bots) == "admin"


def test_selected_bot_snapshot_survives_actual_json_save_and_reload(monkeypatch):
    import sqlalchemy as sa
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.infrastructure.repositories.factory.ProjectTemplateRepository import ProjectTemplateRepository

    engine = sa.create_engine("sqlite://")
    ProjectTemplate.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    repo = ProjectTemplateRepository(None, None)
    template = ProjectTemplate(
        name="Stored",
        columns=["Queue"],
        internal_bots=[
            {
                "internal_bot_uid": "old",
                "bot_type": "project_chat",
                "prompt": "Keep instructions",
                "use_default_prompt": False,
            }
        ],
    )
    repo.insert(template)
    bot = SimpleNamespace(bot_type=InternalBotType.ProjectChat, get_uid=lambda: "selected")
    monkeypatch.setattr(
        InfraHelper,
        "get_by_id_like",
        lambda model, uid: repo.get_by_name("Stored") if model is ProjectTemplate else bot,
    )
    service = ProjectTemplateService(None, None, SimpleNamespace(project_template=repo))
    service.save_columns("Stored", [{"name": "Queue"}], "template", internal_bot_uids=["selected"])
    loaded = repo.get_by_name("Stored")
    assert loaded.internal_bots == [
        {
            "internal_bot_uid": "selected",
            "bot_type": "project_chat",
            "prompt": "Keep instructions",
            "use_default_prompt": False,
        }
    ]
    service.save_columns("Stored", [{"name": "Queue"}], "template")
    assert repo.get_by_name("Stored").internal_bots == loaded.internal_bots
    engine.dispose()
