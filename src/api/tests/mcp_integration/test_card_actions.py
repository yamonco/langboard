"""Native facade validation and dispatch retain canonical authorization."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import AuthorizationError
from langboard.mcp_integration.Providers import create_agent_core_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.CardActionsMcp import CARD_ACTION_COMMANDS
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize(
    "change,command,expected",
    [
        ({"action": "assign", "assign_user_uids": []}, "set_card_people_and_labels", {"assign_user_uids": []}),
        ({"action": "label", "label_uids": ["label"]}, "set_card_people_and_labels", {"label_uids": ["label"]}),
        ({"action": "title", "title": " New title "}, "change_card_details", {"title": "New title"}),
        ({"action": "deadline", "deadline_at": ""}, "change_card_details", {"deadline_at": ""}),
        (
            {"action": "move", "column_uid": "column", "order": 0},
            "change_card_order_or_move_column",
            {"column_uid": "column", "order": 0},
        ),
        (
            {"action": "description_replace", "description": "    code\n", "expected_revision": "a" * 64},
            "replace_card_description",
            {"description": "    code\n", "expected_revision": "a" * 64},
        ),
        ({"action": "archive"}, "archive_card", {}),
        ({"action": "delete"}, "delete_card", {}),
        (
            {"action": "attachment_update", "attachment_uid": "file", "order": 0},
            "update_card_attachment",
            {"attachment_uid": "file", "order": 0},
        ),
        (
            {"action": "attachment_delete", "attachment_uid": "file"},
            "delete_card_attachment",
            {"attachment_uid": "file"},
        ),
        (
            {"action": "attachment_upload", "filename": "a.png", "file_data_base64": "AA=="},
            "upload_card_attachment",
            {"filename": "a.png", "file_data_base64": "AA=="},
        ),
    ],
)
async def test_native_card_action_catalog_and_dispatch_without_tool_group(monkeypatch, change, command, expected):
    calls = []
    original = McpTool.get_tool("update_card")

    def handler(**kwargs):
        calls.append(kwargs)
        return {"applied": True}

    metadata = {"handler": handler, "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"update_card": original})
    monkeypatch.setattr(
        McpTool, "get_tool", lambda name: original if name == "update_card" else metadata if name == command else None
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture-user")
    checked = []
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, fn, **kwargs: checked.append(fn) or True)
    server = FastMCP("Native card actions")
    server.add_provider(create_agent_core_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture-user"})
    try:
        async with Client(server) as client:
            catalog = await client.list_tools()
            assert [tool.name for tool in catalog] == ["update_card"]
            assert len(catalog[0].input_schema["properties"]["change"]["oneOf"]) == len(CARD_ACTION_COMMANDS)
            result = await client.call_tool(
                "update_card", {"project_uid": "project", "card_uid": "card", "change": change}
            )
            assert result.structured_content == {"applied": True}
        assert calls == [{"project_uid": "project", "card_uid": "card", **expected}]
        assert checked[-1] is handler
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "change",
    [
        {"action": "archive", "title": "accidental field"},
        {"action": "label", "label_uids": [""]},
        {"action": "move", "column_uid": "column", "order": True},
        {"action": "description_replace", "description": "body"},
        {"action": "attachment_update", "attachment_uid": "file"},
    ],
)
async def test_invalid_actions_never_dispatch(change):
    from langboard.mcp_tools.CardActionsMcp import CardChange
    from pydantic import TypeAdapter, ValidationError

    with pytest.raises(ValidationError):
        TypeAdapter(CardChange).validate_python(change)


async def test_facade_does_not_bypass_command_role_denial(monkeypatch):
    from langboard.mcp_tools.CardActionsMcp import DeleteCard, update_card

    def forbidden(**kwargs):
        pytest.fail("Denied command must not run")

    monkeypatch.setattr(
        McpTool, "get_tool", lambda name: {"handler": forbidden, "exclude": [], "accessible_type": "all"}
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: False)
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture-user"})
    try:
        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await update_card("project", "card", DeleteCard(action="delete"))
    finally:
        mcp_auth_context.reset(token)


async def test_delete_uses_native_delete_acl_and_never_runs_on_read_permission(monkeypatch):
    from langboard.mcp_integration.RoleFilter import McpRoleFilter
    from langboard.mcp_tools.CardActionsMcp import DeleteCard, update_card
    from langboard.mcp_tools.CardMcp import delete_card
    from langboard_shared.domain.models.ProjectRole import ProjectRoleAction

    metadata = McpTool.get_tool("delete_card")
    assert metadata["handler"] is delete_card
    checked = []

    def check_role(actor, handler, **arguments):
        required = McpRoleFilter.get_filtered(handler)[1]
        checked.append(required)
        return ProjectRoleAction.CardDelete.value not in required

    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: True)
    monkeypatch.setattr(McpServer, "_validate_role", check_role)
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "read-only-fixture"})
    try:
        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await update_card("project", "card", DeleteCard(action="delete"))
        assert checked == [[ProjectRoleAction.CardDelete.value]]
    finally:
        mcp_auth_context.reset(token)
