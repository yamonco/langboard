"""Native discovery absorbs plugin search, projection and link behavior."""

from types import SimpleNamespace
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration import ProjectDiscovery
from langboard.mcp_integration.Providers import create_native_domain_provider
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import ProjectMcp


@pytest.mark.parametrize("modern", [True, False])
async def test_native_project_discovery_preserves_authorized_search_and_legacy(monkeypatch, modern):
    actor = object()
    authorized = [
        {
            "uid": "p/one",
            "title": "Straße 랭보드",
            "project_type": "Other",
            "starred": False,
            "current_auth_role_actions": ["read"],
            "description": "large board body",
            "owner_uid": "private",
        }
    ]
    calls = []

    def get_list(user):
        assert user is actor
        calls.append(user)
        return authorized, []

    service = SimpleNamespace(project=SimpleNamespace(get_api_list=get_list))
    metadata = McpTool.get_tool("get_projects")
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"get_projects": metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: None)
    monkeypatch.setattr(ProjectDiscovery, "Env", SimpleNamespace(PUBLIC_UI_URL="https://board.example/"))

    def wrap(name, handler):
        from functools import wraps
        from inspect import signature

        @wraps(handler)
        async def call(**kwargs):
            return handler(user=actor, service=service, **kwargs)

        call.__signature__ = signature(handler).replace(
            parameters=[p for name, p in signature(handler).parameters.items() if name not in {"user", "service"}]
        )
        return call

    server = FastMCP("Native project discovery fixture")
    server.add_provider(create_native_domain_provider(wrap, modern_annotations=modern))
    async with Client(server) as client:
        tool = (await client.list_tools())[0]
        assert ("query" in tool.input_schema["properties"]) is modern
        data = (await client.call_tool("get_projects", {})).structured_content
        if not modern:
            assert data == {"projects": authorized}
            return
        row = data["projects"][0]
        assert set(row) == {
            "uid",
            "title",
            "project_type",
            "starred",
            "current_auth_role_actions",
            "project_url",
            "project_link_markdown",
        }
        assert row["project_url"] == "https://board.example/board/p%2Fone"
        assert row["project_link_markdown"] == "[Open board in Langboard](https://board.example/board/p%2Fone)"
        for query in [" STRASSE ", "랭보드"]:
            result = await client.call_tool("get_projects", {"query": query})
            assert result.structured_content == data
        result = await client.call_tool("get_projects", {"query": "No access board"})
        assert result.structured_content == {"projects": []}
        before = len(calls)
        for query in [" ", "x" * 101, 1]:
            with pytest.raises(ToolError):
                await client.call_tool("get_projects", {"query": query})
        assert len(calls) == before


@pytest.mark.parametrize("query", ["", " ", "x" * 101, 1])
def test_direct_project_search_rejects_invalid_query_before_read(query):
    with pytest.raises(ValueError, match="Project query"):
        ProjectMcp.get_projects(object(), object(), query=query)
