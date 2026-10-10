"""Exercise the compatibility provider through actual FastMCP dispatch."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import (
    AGENT_CORE_TOOLS,
    create_agent_core_provider,
    create_compatibility_provider,
    create_raw_primitive_provider,
)
from langboard.mcp_integration.Server import McpServer, _create_fastmcp
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


async def test_modern_annotations_reach_catalog_and_raw_search_without_changing_legacy():
    import json
    from langboard.Loader import ModuleLoader
    from langboard.mcp_integration.Annotations import READ_ONLY_TOOLS

    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    registered = set(McpTool.get_tools())
    assert READ_ONLY_TOOLS - {"search_raw_tools"} <= registered
    token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=list(registered))})
    try:
        catalogs = {}
        for profile in ("compatibility", "agent", "raw"):
            _, server = McpServer.get_http_app(profile)
            async with Client(server) as client:
                catalogs[profile] = {tool.name: tool for tool in await client.list_tools()}
                if profile == "raw":
                    result = await client.call_tool("search_raw_tools", {"pattern": r"^get_public_card_metadata\b"})
                    definition = json.loads(result.content[0].text)[0]
                    assert definition["annotations"]["readOnlyHint"] is True
        assert all(tool.annotations is None for tool in catalogs["compatibility"].values())
        read = catalogs["agent"]["get_card_bundle"].annotations
        assert read.read_only_hint is True and read.destructive_hint is False and read.idempotent_hint is True
        write = catalogs["agent"]["create_card"].annotations
        assert write.read_only_hint is False and write.destructive_hint is True and write.idempotent_hint is False
        assert catalogs["raw"]["search_raw_tools"].annotations.read_only_hint is True
        assert catalogs["raw"]["call_raw_tool"].annotations.read_only_hint is False
        assert catalogs["raw"]["call_raw_tool"].annotations.idempotent_hint is False
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize("role_allowed", [True, False])
async def test_provider_preserves_wrapped_dispatch_and_tool_group_deny(monkeypatch, role_allowed):
    calls = []

    def record(value: int) -> dict[str, int]:
        calls.append(value)
        return {"value": value}

    metadata = {"handler": record, "description": "Record a value", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"record": metadata, "denied": metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata if name in {"record", "denied"} else None)
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


async def test_registered_profiles_partition_catalog_without_changing_schemas():
    from langboard.Loader import ModuleLoader

    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    registered = set(McpTool.get_tools())
    assert AGENT_CORE_TOOLS <= registered
    token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=list(registered))})
    try:
        catalogs = {}
        for profile in ("compatibility", "agent", "raw"):
            if profile == "raw":
                server = _create_fastmcp()
                server.add_provider(create_raw_primitive_provider(McpServer._wrap_tool))
            else:
                _, server = McpServer.get_http_app(profile)
            async with Client(server) as client:
                catalogs[profile] = {tool.name: tool.input_schema for tool in await client.list_tools()}
        assert set(catalogs["agent"]) == AGENT_CORE_TOOLS
        assert set(catalogs["raw"]) == registered - AGENT_CORE_TOOLS
        modern = {**catalogs["agent"], **catalogs["raw"]}
        assert "profile" in modern["get_card_bundle"]["properties"]
        assert "profile" not in catalogs["compatibility"]["get_card_bundle"]["properties"]
        modern["get_card_bundle"]["properties"].pop("profile")
        assert modern == catalogs["compatibility"]
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize("role_allowed", [True, False])
async def test_raw_search_respects_grants_and_proxy_rechecks_current_authorization(monkeypatch, role_allowed):
    import json

    calls = []

    def record(value: int) -> dict[str, int]:
        calls.append(value)
        return {"value": value}

    metadata = {"handler": record, "description": "Record", "exclude": [], "accessible_type": "all"}
    names = {"archive_card", "delete_card", "get_projects"}

    def archive(value: int) -> dict[str, str]:
        calls.append(value)
        return {"message": "Archived"}

    registry = dict.fromkeys(names, metadata)
    registry["archive_card"] = {**metadata, "handler": archive}
    monkeypatch.setattr(McpTool, "get_tools", lambda: registry)
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata if name in names else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, handler, **kwargs: role_allowed)
    _, server = McpServer.get_http_app("raw")
    group = SimpleNamespace(activated_at=object(), tools=["archive_card", "get_projects"])
    token = mcp_auth_context.set({"user_or_bot": object(), "tool_group": group})
    try:
        async with Client(server) as client:
            assert {tool.name for tool in await client.list_tools()} == {"search_raw_tools", "call_raw_tool"}
            search = await client.call_tool("search_raw_tools", {"pattern": ".*"})
            definitions = json.loads(search.content[0].text)
            assert [tool["name"] for tool in definitions] == ["archive_card"]
            assert definitions[0]["inputSchema"]["properties"]["value"]["type"] == "integer"
            if role_allowed:
                result = await client.call_tool("call_raw_tool", {"name": "archive_card", "arguments": {"value": 3}})
                assert result.structured_content == {"message": "Archived"}
            else:
                with pytest.raises(ToolError):
                    await client.call_tool("call_raw_tool", {"name": "archive_card", "arguments": {"value": 3}})
            for denied in ("delete_card", "get_projects", "call_raw_tool"):
                with pytest.raises(ToolError):
                    await client.call_tool("call_raw_tool", {"name": denied, "arguments": {"value": 4}})
            group.tools = []
            revoked = await client.call_tool("search_raw_tools", {"pattern": ".*"})
            assert not revoked.content
            with pytest.raises(ToolError):
                await client.call_tool("call_raw_tool", {"name": "archive_card", "arguments": {"value": 5}})
            group.activated_at = None
            with pytest.raises(ToolError):
                await client.call_tool("search_raw_tools", {"pattern": ".*"})
            assert calls == ([3] if role_allowed else [])
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize("path", ["/mcp/stream", "/mcp/agent/stream", "/mcp/raw/stream"])
def test_mounted_profiles_retain_http_authentication(monkeypatch, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.App import App
    from langboard.Loader import ModuleLoader
    from langboard_shared.helpers import MiddlewareHelper

    monkeypatch.setattr(ModuleLoader, "load", lambda *args, **kwargs: {})
    monkeypatch.setattr(MiddlewareHelper, "validate_auth", lambda scope, *, allow_oidc=False: 401)
    app = App.__new__(App)
    app.config = SimpleNamespace(is_restarting=False)
    app.api = FastAPI()
    app._init_mcp_server()
    app._init_api_routes()
    with TestClient(app.api) as client:
        response = client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401


@pytest.mark.parametrize(
    "factory,visible,hidden",
    [
        (create_agent_core_provider, "get_projects", "archive_card"),
        (create_raw_primitive_provider, "archive_card", "get_projects"),
        (create_compatibility_provider, "get_projects", None),
    ],
)
@pytest.mark.parametrize("role_allowed", [True, False])
async def test_profiles_preserve_domain_dispatch_and_deny_hidden_or_ungranted_calls(
    monkeypatch,
    factory,
    visible,
    hidden,
    role_allowed,
):
    calls = []

    def record(value: int) -> dict[str, int]:
        calls.append(value)
        return {"value": value}

    metadata = {"handler": record, "description": "Record", "exclude": [], "accessible_type": "all"}
    names = {"get_projects", "archive_card", "denied"}

    def archive(value: int) -> dict[str, str]:
        calls.append(value)
        return {"message": "Archived"}

    registry = dict.fromkeys(names, metadata)
    registry["archive_card"] = {**metadata, "handler": archive}
    monkeypatch.setattr(McpTool, "get_tools", lambda: registry)
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata if name in names else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, handler, **kwargs: role_allowed)
    server = _create_fastmcp()
    server.add_provider(factory(McpServer._wrap_tool))
    token = mcp_auth_context.set(
        {
            "user_or_bot": object(),
            "tool_group": SimpleNamespace(activated_at=object(), tools=["get_projects", "archive_card"]),
        }
    )
    try:
        async with Client(server) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == ({visible} if hidden else {"get_projects", "archive_card"})
            if role_allowed:
                result = await client.call_tool(visible, {"value": 3})
                assert result.structured_content == (
                    {"message": "Archived"} if visible == "archive_card" else {"value": 3}
                )
            else:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool(visible, {"value": 3})
            if hidden:
                with pytest.raises(ToolError):
                    await client.call_tool(hidden, {"value": 4})
            with pytest.raises(ToolError):
                await client.call_tool("denied", {"value": 5})
            assert calls == ([3] if role_allowed else [])
    finally:
        mcp_auth_context.reset(token)


async def test_provider_exposes_server_owned_workflow_resource_and_prompt(monkeypatch):
    monkeypatch.setattr(McpTool, "get_tools", lambda: {})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: None)
    server = _create_fastmcp()
    server.add_provider(create_compatibility_provider(McpServer._wrap_tool))
    async with Client(server) as client:
        resources = await client.list_resources()
        assert [str(resource.uri) for resource in resources] == ["langboard://policy/workflow"]
        resource = await client.read_resource("langboard://policy/workflow")
        assert "workflow_stage_status" in str(resource)
        prompts = await client.list_prompts()
        assert [prompt.name for prompt in prompts] == ["apply_workflow_policy"]
        prompt = await client.get_prompt("apply_workflow_policy", {})
        assert "get_project_identity" in str(prompt)


@pytest.mark.parametrize("granted", [True, False])
async def test_card_policy_resource_reuses_current_query_and_rejects_ungranted_reads(monkeypatch, granted):
    state = {"workflow": {"workflow_guidance": "Review first"}, "work_state": {"verification_state": "unverified"}}
    calls = []

    async def bundle(**kwargs):
        calls.append(kwargs)
        return {"card": state}

    monkeypatch.setattr(McpTool, "get_tools", lambda: {})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: {"handler": bundle} if name == "get_card_bundle" else None)
    server = _create_fastmcp()
    server.add_provider(create_compatibility_provider(lambda name, handler: handler))
    token = mcp_auth_context.set(
        {"tool_group": SimpleNamespace(activated_at=object(), tools=["get_card_bundle"] if granted else [])}
    )
    try:
        async with Client(server) as client:
            if granted:
                resource = await client.read_resource("langboard://projects/project/cards/card/workflow")
                assert "Review first" in str(resource)
                state["workflow"]["workflow_guidance"] = "Changed server guidance"
                prompt = await client.get_prompt("apply_card_workflow", {"project_uid": "project", "card_uid": "card"})
                assert "Changed server guidance" in str(prompt)
                assert len(calls) == 2
                assert calls[0] == {"project_uid": "project", "card_uid": "card", "include": []}
            else:
                with pytest.raises(Exception, match="get_card_bundle is not allowed"):
                    await client.read_resource("langboard://projects/project/cards/card/workflow")
                with pytest.raises(Exception, match="get_card_bundle is not allowed"):
                    await client.get_prompt("apply_card_workflow", {"project_uid": "project", "card_uid": "card"})
                assert calls == []
    finally:
        mcp_auth_context.reset(token)
