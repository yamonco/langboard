"""Independent native clients use wiki views without plugin orchestration."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import create_native_agent_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.WikiActionsMcp import read_wiki
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("denied", [False, True])
async def test_native_wiki_views_keep_canonical_permission_and_pagination(monkeypatch, denied):
    original = McpTool.get_tool("read_wiki")
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return {"content": "한글", "next_cursor": "next-page"}

    metadata = {"handler": query, "exclude": [], "accessible_type": "user"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"read_wiki": original})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: original if name == "read_wiki" else metadata)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture")
    monkeypatch.setattr(
        McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied or handler is read_wiki
    )
    server = FastMCP("Native wiki views fixture")
    server.add_provider(create_native_agent_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture"})
    try:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert tools["read_wiki"].annotations.read_only_hint
            for view, extra, expected in [
                ("content", {}, {"limit": 8000}),
                ("history", {"cursor": "page", "limit": 50}, {"cursor": "page", "limit": 50}),
                (
                    "revision",
                    {"revision_uid": "revision", "side": "before"},
                    {"revision_uid": "revision", "side": "before", "limit": 8000},
                ),
            ]:
                args = {"project_uid": "project", "wiki_uid": "wiki", "view": view, **extra}
                if denied:
                    with pytest.raises(ToolError, match="Insufficient permissions"):
                        await client.call_tool("read_wiki", args)
                    assert not calls
                else:
                    result = await client.call_tool("read_wiki", args)
                    assert result.structured_content == {"content": "한글", "next_cursor": "next-page"}
                    assert calls[-1] == {"project_uid": "project", "wiki_uid": "wiki", "cursor": None, **expected}
            for extra in [
                {"view": "content", "revision_uid": "revision"},
                {"view": "history", "side": "before"},
                {"view": "history", "limit": 51},
                {"view": "revision"},
                {"view": "revision", "revision_uid": " "},
                {"limit": True},
                {"limit": "20"},
            ]:
                before = len(calls)
                with pytest.raises(ToolError):
                    await client.call_tool("read_wiki", {"project_uid": "project", "wiki_uid": "wiki", **extra})
                assert len(calls) == before
    finally:
        mcp_auth_context.reset(token)
