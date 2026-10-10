"""Read limits reject oversized output while retaining schemas and command receipts."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult
from langboard.mcp_integration.ResponseBudget import ReadResponseBudgetMiddleware
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from pydantic_core import to_json


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("oversized", [False, True])
async def test_read_result_exact_byte_boundary_and_multibyte_cursor_preservation(raw, oversized):
    result = ToolResult(content="한글" * 250, structured_content={"next_cursor": "cursor"}, meta={"custom": True})
    size = len(to_json(result, fallback=str))
    middleware = ReadResponseBudgetMiddleware(size - int(oversized))
    context = SimpleNamespace(
        message=SimpleNamespace(
            name="call_raw_tool" if raw else "get_card_bundle", arguments={"name": "get_card_bundle"}
        )
    )

    async def next_call(_):
        return result

    actual = await middleware.on_call_tool(context, next_call)
    if oversized:
        assert actual.is_error and actual.structured_content is None
        assert actual.meta["response_limit"] == {
            "max_bytes": size - 1,
            "actual_bytes": size,
            "next_action": "narrow_query",
        }
        assert "한글" not in str(actual.content)
        assert len(to_json(actual)) < middleware.max_bytes
    else:
        assert actual is result


@pytest.mark.parametrize("name", ["create_card", "get_project", "unknown"])
async def test_large_command_result_is_never_replaced(name):
    result = ToolResult(content="Private command output" * 300, meta={"mutation_receipt": {"outcome": "applied"}})
    context = SimpleNamespace(message=SimpleNamespace(name=name, arguments={}))

    async def next_call(_):
        return result

    assert await ReadResponseBudgetMiddleware(1024).on_call_tool(context, next_call) is result


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
async def test_native_transport_schema_and_oversize_error_preserve_legacy(monkeypatch, profile):
    name = "get_project_columns" if profile == "raw" else "get_projects"

    def handler() -> dict:
        return {"rows": "한" * 400_000, "next_cursor": "next"}

    metadata = {"handler": handler, "description": "Query", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            if profile == "raw":
                search = await client.call_tool("search_raw_tools", {"pattern": "^" + name + r"\b"})
                assert json.loads(search.content[0].text)[0]["outputSchema"]
            else:
                assert (await client.list_tools())[0].output_schema
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {}} if profile == "raw" else {},
                raise_on_error=False,
            )
            if profile == "compatibility":
                assert not result.is_error and result.structured_content["next_cursor"] == "next"
            else:
                assert result.is_error and result.structured_content is None
                assert result.meta["response_limit"]["next_action"] == "narrow_query"
                assert "mutation_receipt" not in result.meta
    finally:
        mcp_auth_context.reset(token)
