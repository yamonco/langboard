"""Native checklist schema dispatch cannot bypass command authorization."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import AuthorizationError, ToolError
from langboard.mcp_integration.Providers import create_agent_core_provider
from langboard.mcp_integration.RoleFilter import McpRoleFilter
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.ChecklistActionsMcp import (
    CHECKLIST_ACTION_COMMANDS,
    PromoteItem,
    change_card_checklist,
)
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"action": "create_list", "title": " Tasks "}, {"title": "Tasks"}),
        ({"action": "add_item", "checklist_uid": "list", "title": "Task"}, {"checklist_uid": "list", "title": "Task"}),
        (
            {"action": "update_list", "checklist_uid": "list", "is_checked": False},
            {"checklist_uid": "list", "is_checked": False},
        ),
        ({"action": "delete_list", "checklist_uid": "list"}, {"checklist_uid": "list"}),
        (
            {"action": "set_completed", "checkitem_uid": "item", "is_checked": False},
            {"checkitem_uid": "item", "is_checked": False},
        ),
        (
            {"action": "update_item", "checkitem_uid": "item", "deadline_at": ""},
            {"checkitem_uid": "item", "deadline_at": ""},
        ),
        ({"action": "delete_item", "checkitem_uid": "item"}, {"checkitem_uid": "item"}),
        (
            {"action": "promote", "checkitem_uid": "item", "project_column_uid": "column"},
            {"checkitem_uid": "item", "project_column_uid": "column"},
        ),
    ],
)
async def test_native_checklist_catalog_and_dispatch_without_tool_group(monkeypatch, change, expected):
    calls = []
    original = McpTool.get_tool("change_card_checklist")
    command = CHECKLIST_ACTION_COMMANDS[change["action"]]

    def handler(**kwargs):
        calls.append(kwargs)
        return {"applied": True}

    metadata = {"handler": handler, "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"change_card_checklist": original})
    monkeypatch.setattr(
        McpTool,
        "get_tool",
        lambda name: original if name == "change_card_checklist" else metadata if name == command else None,
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture-user")
    checked = []
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, fn, **kwargs: checked.append(fn) or True)
    server = FastMCP("Native checklist actions")
    server.add_provider(create_agent_core_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture-user"})
    try:
        async with Client(server) as client:
            catalog = await client.list_tools()
            assert [tool.name for tool in catalog] == ["change_card_checklist"]
            assert len(catalog[0].input_schema["properties"]["change"]["oneOf"]) == 8
            result = await client.call_tool(
                "change_card_checklist", {"project_uid": "project", "card_uid": "card", "change": change}
            )
            assert result.structured_content == {"applied": True}
            for invalid in (
                {"action": "delete_item", "checkitem_uid": "item", "title": "unrelated"},
                {"action": "set_completed", "checkitem_uid": "item", "is_checked": "false"},
                {"action": "update_list", "checklist_uid": "list"},
                {"action": "update_item", "checkitem_uid": "item", "title": None},
                {"action": "add_item", "checklist_uid": "list", "title": " "},
                {"action": "promote", "checkitem_uid": "item", "project_column_uid": " "},
            ):
                with pytest.raises(ToolError):
                    await client.call_tool(
                        "change_card_checklist", {"project_uid": "project", "card_uid": "card", "change": invalid}
                    )
        assert calls == [{"project_uid": "project", "card_uid": "card", **expected}]
        assert checked[-1] is handler
    finally:
        mcp_auth_context.reset(token)


async def test_promotion_retains_canonical_update_permission(monkeypatch):
    from langboard.mcp_tools.CardMcp import cardify_card_checkitem

    metadata = McpTool.get_tool("cardify_card_checkitem")
    assert metadata["handler"] is cardify_card_checkitem
    checked = []

    def check_role(actor, handler, **arguments):
        checked.append(handler)
        actions = McpRoleFilter.get_filtered(handler)[1]
        assert actions == [ProjectRoleAction.CardUpdate.value]
        return False

    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", check_role)
    monkeypatch.setattr(
        McpServer, "_inject_kwargs", lambda *args: pytest.fail("Denied command must not create services")
    )
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture-user"})
    try:
        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await change_card_checklist(
                "project", "card", PromoteItem(action="promote", checkitem_uid="item", project_column_uid="column")
            )
        assert checked == [cardify_card_checkitem]
    finally:
        mcp_auth_context.reset(token)
