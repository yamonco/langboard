"""Exercise the compatibility provider through actual FastMCP dispatch."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import create_compatibility_provider
from langboard.mcp_integration.Server import McpServer, _create_fastmcp
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("role_allowed", [True, False])
async def test_provider_preserves_wrapped_dispatch_and_tool_group_deny(monkeypatch, role_allowed):
    calls = []

    def record(value: int) -> dict[str, int]:
        calls.append(value)
        return {"value": value}

    metadata = {"handler": record, "description": "Record a value", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"record": metadata, "denied": metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, handler, **kwargs: role_allowed)
    server = _create_fastmcp()
    server.add_provider(create_compatibility_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=["record"])}
    )
    try:
        async with Client(server) as client:
            catalog = await client.list_tools()
            assert [tool.name for tool in catalog] == ["record"]
            assert catalog[0].input_schema["properties"]["value"]["type"] == "integer"
            if role_allowed:
                result = await client.call_tool("record", {"value": 3})
                assert result.structured_content == {"value": 3}
            else:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool("record", {"value": 3})
            with pytest.raises(ToolError):
                await client.call_tool("denied", {"value": 4})
            assert calls == ([3] if role_allowed else [])
    finally:
        mcp_auth_context.reset(token)
