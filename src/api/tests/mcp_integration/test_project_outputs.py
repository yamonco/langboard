"""Project detail contracts retain native identity variants and side effects."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.ProjectOutputs import PROJECT_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import ProjectMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import (
    BotSchedule,
    Project,
    ProjectBotSchedule,
    ProjectBotScope,
    ProjectLabel,
    User,
)
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.domain.models.BotSchedule import BotScheduleStatus
from pydantic import TypeAdapter, ValidationError


def native_result(actor):
    project = Project(id=123, owner_id=456, title="Board")
    owner = User(id=456, firstname="User", lastname="Name", email="fixture@example.invalid", password="fixture")
    label = ProjectLabel(
        id=789,
        project_id=project.id,
        name="Contract",
        color="#123456",
        description="Development interface",
        global_label_id=790,
        global_display={"emoji": "📜", "translations": {"ko": {"name": "계약"}}},
    )
    response = {
        **project.api_response(),
        "all_members": [
            owner.api_response(),
            User.create_unknown_user_api_response("deleted"),
            User.create_email_user_api_response(owner.id, "invited@example.invalid"),
        ],
        "invited_member_uids": [owner.get_uid()],
        "labels": [label.api_response()],
    }
    if isinstance(actor, User):
        response["current_auth_role_actions"] = ["*"]
    scope = ProjectBotScope(id=800, project_id=project.id, bot_id=801, conditions=[BotTriggerCondition.CardCreated])
    schedule = BotSchedule(id=802, bot_id=801, status=BotScheduleStatus.Started, interval_str="* * * * *")
    assigned_schedule = ProjectBotSchedule(id=803, project_id=project.id, bot_schedule_id=schedule.id)
    return project, {
        "project": response,
        "project_bot_scopes": [scope.api_response()],
        "project_bot_schedules": [{**schedule.api_response(), **assigned_schedule.api_response()}],
    }


@pytest.mark.parametrize("user", [True, False])
def test_native_projection_keeps_member_variants_and_bot_role_omission(user):
    actor = (
        User(id=456, firstname="User", lastname="Name", email="fixture@example.invalid", password="fixture")
        if user
        else object()
    )
    _, expected = native_result(actor)
    actual = PROJECT_OUTPUTS["get_project"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert ("current_auth_role_actions" in actual["project"]) is user
    assert "created_at" not in actual["project"]["all_members"][1]
    assert actual["project"]["labels"][0]["global_display"]["translations"]["ko"]["name"] == "계약"


def test_project_contract_rejects_private_or_malformed_nested_fields():
    _, expected = native_result(object())
    expected["project"]["all_members"][0]["password"] = "not-a-real-secret"
    with pytest.raises(ValidationError):
        PROJECT_OUTPUTS["get_project"].model_validate(expected)
    del expected["project"]["all_members"][0]["password"]
    expected["project_bot_scopes"][0]["is_frozen"] = 1
    with pytest.raises(ValidationError):
        PROJECT_OUTPUTS["get_project"].model_validate(expected)


@pytest.mark.parametrize("profile", ["raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_project_native_handler_side_effects_and_postsave_unknown(monkeypatch, profile, malformed):
    actor = User(id=456, firstname="User", lastname="Name", email="fixture@example.invalid", password="fixture")
    project, expected = native_result(actor)
    effects = []

    def details(*args):
        assert args == (actor, "board", False)
        effects.append("initialize")
        if malformed:
            expected["project"]["dock_revision"] = "invalid"
        return project, expected["project"]

    service = SimpleNamespace(
        project=SimpleNamespace(
            get_details=details,
            get_api_bot_scope_list=lambda value: expected["project_bot_scopes"],
            get_api_bot_schedule_list=lambda value: expected["project_bot_schedules"],
            set_last_view=lambda *args: effects.append("last_view"),
        )
    )

    def handler(project_uid: str) -> dict:
        return ProjectMcp.get_project(project_uid, actor, service)

    name = "get_project"
    metadata = {"handler": handler, "description": "Details", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": actor, "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            if profile == "raw":
                search = await client.call_tool("search_raw_tools", {"pattern": "^get_project\\b"})
                assert json.loads(search.content[0].text)[0]["outputSchema"]["properties"]["project"]
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"project_uid": "board"}} if profile == "raw" else {"project_uid": "board"},
                raise_on_error=False,
            )
            assert effects == ["initialize", "last_view"]
            if malformed and profile == "raw":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                assert result.structured_content == TypeAdapter(dict).dump_python(expected, mode="json")
    finally:
        mcp_auth_context.reset(token)
