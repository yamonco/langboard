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
