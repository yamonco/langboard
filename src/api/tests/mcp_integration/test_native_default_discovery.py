"""Default native discovery retains callable commands and canonical authorization."""

import json
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.Loader import ModuleLoader
from langboard.mcp_integration.Providers import (
    AGENT_CORE_TOOLS,
    create_native_agent_provider,
    create_native_domain_provider,
)
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("denied", [False, True])
async def test_native_default_search_and_direct_calls_preserve_acl(monkeypatch, denied):
    calls = []

    def core() -> dict:
        return {"fixture": "core"}

    def primitive(value: int) -> dict:
        calls.append(value)
        return {"applied": value}

    registry = {
        name: {"handler": handler, "description": name, "exclude": [], "accessible_type": "user"}
        for name, handler in [("diagnose_connection", core), ("fixture_primitive", primitive)]
    }
    monkeypatch.setattr(McpTool, "get_tools", lambda: registry)
    monkeypatch.setattr(McpTool, "get_tool", lambda name: registry.get(name))
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "user")
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied or handler is core)
    server = FastMCP("Native default discovery fixture")
    server.add_provider(create_native_agent_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "user"})
    try:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {"diagnose_connection", "search_raw_tools", "call_raw_tool"}
            assert tools["search_raw_tools"].annotations.read_only_hint
            assert not tools["call_raw_tool"].annotations.read_only_hint
            search = await client.call_tool("search_raw_tools", {"pattern": r"^fixture_primitive\b"})
            definition = json.loads(search.content[0].text)[0]
            assert definition["name"] == "fixture_primitive"
            assert definition["inputSchema"]["properties"]["value"]["type"] == "integer"
            pinned = await client.call_tool("search_raw_tools", {"pattern": "diagnose_connection"})
            assert not pinned.content
            for name, arguments in [
                ("fixture_primitive", {"value": 7}),
                ("call_raw_tool", {"name": "fixture_primitive", "arguments": {"value": 8}}),
            ]:
                if denied:
                    with pytest.raises(ToolError, match="Insufficient permissions"):
                        await client.call_tool(name, arguments)
                else:
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error
            assert calls == ([] if denied else [7, 8])
            with pytest.raises(ToolError):
                await client.call_tool("call_raw_tool", {"name": "call_raw_tool", "arguments": {}})
            with pytest.raises(ToolError):
                await client.call_tool("call_raw_tool", {"name": "fixture_primitive", "arguments": {"value": "bad"}})
            assert calls == ([] if denied else [7, 8])
    finally:
        mcp_auth_context.reset(token)


async def test_real_native_catalog_keeps_every_core_tool_and_reduces_initial_definitions():
    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": object()})
    try:
        catalogs = []
        for default in [False, True]:
            server = FastMCP("Native catalog measurement")
            provider = (
                create_native_agent_provider(McpServer._wrap_tool)
                if default
                else create_native_domain_provider(McpServer._wrap_tool, modern_annotations=True)
            )
            server.add_provider(provider)
            async with Client(server) as client:
                tools = await client.list_tools()
                catalogs.append(
                    {tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools}
                )
        full, initial = catalogs
        assert set(initial) == (set(full) & AGENT_CORE_TOOLS) | {"search_raw_tools", "call_raw_tool"}
        assert len(initial) < len(full)
        assert len(json.dumps(initial)) < len(json.dumps(full))
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize("name", ["get_employee_status", "list_employees"])
@pytest.mark.parametrize("denied", [False, True])
async def test_optional_directory_remains_searchable_with_original_authorization(monkeypatch, name, denied):
    calls = []

    def directory() -> dict:
        calls.append(name)
        return {"policy_status": "unknown"}

    registry = {name: {"handler": directory, "description": name, "exclude": [], "accessible_type": "user"}}
    monkeypatch.setattr(McpTool, "get_tools", lambda: registry)
    monkeypatch.setattr(McpTool, "get_tool", lambda key: registry.get(key))
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, key: actor == "user")
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: not denied)
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "user"})
    try:
        for compact in [False, True]:
            server = FastMCP("Optional directory")
            server.add_provider(
                create_native_agent_provider(McpServer._wrap_tool)
                if compact else create_native_domain_provider(McpServer._wrap_tool)
            )
            async with Client(server) as client:
                visible = {tool.name for tool in await client.list_tools()}
                assert (name in visible) is (not compact)
                if compact:
                    result = await client.call_tool("search_raw_tools", {"pattern": rf"^{name}\b"})
                    assert json.loads(result.content[0].text)[0]["name"] == name
                invocations = [(name, {})]
                if compact:
                    invocations.append(("call_raw_tool", {"name": name, "arguments": {}}))
                for command, arguments in invocations:
                    if denied:
                        with pytest.raises(ToolError, match="Insufficient permissions"):
                            await client.call_tool(command, arguments)
                    else:
                        assert not (await client.call_tool(command, arguments)).is_error
        assert calls == ([] if denied else [name] * 3)
    finally:
        mcp_auth_context.reset(token)
