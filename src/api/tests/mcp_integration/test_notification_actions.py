"""Native notification scope rejects ambiguity before dispatch."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import create_agent_core_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.NotificationActionsMcp import NOTIFICATION_READ_COMMANDS, NotificationReadChange
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize("change", [{"scope": "one", "notification_uid": " owned "}, {"scope": "all"}])
@pytest.mark.parametrize("denied", [False, True])
async def test_native_notification_scope_dispatch(monkeypatch, change, denied):
    original = McpTool.get_tool("mark_notifications_read")
    calls = []

    def command(**kwargs):
        calls.append(kwargs)
        return {"read": True}

    target = NOTIFICATION_READ_COMMANDS[change["scope"]]
    metadata = {"handler": command, "exclude": [], "accessible_type": "user"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"mark_notifications_read": original})
    monkeypatch.setattr(
        McpTool,
        "get_tool",
        lambda name: original if name == "mark_notifications_read" else metadata if name == target else None,
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "user")
    monkeypatch.setattr(
        McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied or handler is original["handler"]
    )
    server = FastMCP("Notification scope fixture")
    server.add_provider(create_agent_core_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "user"})
    try:
        async with Client(server) as client:
            tool = (await client.list_tools())[0]
            assert tool.name == "mark_notifications_read"
            assert len(tool.input_schema["properties"]["change"]["oneOf"]) == 2
            assert tool.output_schema["properties"]["read"]["const"] is True
            if denied:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool(tool.name, {"change": change})
                assert calls == []
            else:
                result = await client.call_tool(tool.name, {"change": change})
                assert result.structured_content == {"read": True}
                assert calls == ([{"notification_uid": "owned"}] if change["scope"] == "one" else [{}])
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"scope": "one"},
        {"scope": "one", "notification_uid": " "},
        {"scope": "all", "notification_uid": "owned"},
        {"scope": "all", "project_uid": "project"},
        {"scope": "both", "notification_uid": "owned"},
    ],
)
def test_invalid_notification_scope_never_dispatches(change):
    with pytest.raises(ValidationError):
        TypeAdapter(NotificationReadChange).validate_python(change)
