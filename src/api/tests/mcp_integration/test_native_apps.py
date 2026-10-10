"""Native Apps metadata is optional presentation, never domain authorization."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration import McpTool
from langboard.mcp_integration.Apps import WORK_PLAN_URI
from langboard.mcp_integration.Providers import create_compatibility_provider, create_native_agent_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_tools import CardMcp  # noqa: F401
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("denied", [False, True])
async def test_native_plan_app_resource_and_canonical_role_check(monkeypatch, denied):
    original = McpTool.get_tool("preview_card_work_plan")
    calls = []
    plan = {
        "project_uid": "project",
        "anchor_card_uid": "card",
        "new_cards": [{"client_ref": "new:one", "title": "<script>unsafe</script>"}],
    }

    def preview(project_uid: str, plan: dict):
        calls.append({"project_uid": project_uid, "plan": plan})
        return {"revision": "a" * 64, "plan": plan, "counts": {"cards": 1, "cardifications": 0, "checklists": 0}}

    metadata = {**original, "handler": preview}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"preview_card_work_plan": metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: metadata if name == "preview_card_work_plan" else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture")
    monkeypatch.setattr(McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied)
    server = FastMCP("Native work plan App fixture")
    server.add_provider(create_native_agent_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture"})
    try:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert tools["preview_card_work_plan"].meta["ui"]["resourceUri"] == WORK_PLAN_URI
            content = (await client.read_resource(WORK_PLAN_URI))[0]
            assert content.mime_type == "text/html;profile=mcp-app"
            assert content.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
            assert "ui/initialize" in content.text and "textContent" in content.text
            assert "<script>unsafe</script>" not in content.text
            args = {"project_uid": "project", "plan": plan}
            if denied:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool("preview_card_work_plan", args)
                assert not calls
            else:
                result = await client.call_tool("preview_card_work_plan", args)
                assert result.structured_content["plan"]["new_cards"][0]["title"] == "<script>unsafe</script>"
            legacy = FastMCP("Compatibility fixture")
            legacy.add_provider(create_compatibility_provider(McpServer._wrap_tool))
            async with Client(legacy) as old:
                tool = (await old.list_tools())[0]
                assert not tool.meta or "ui" not in tool.meta
                assert WORK_PLAN_URI not in {str(resource.uri) for resource in await old.list_resources()}
    finally:
        mcp_auth_context.reset(token)
