"""Modern card links reach independent clients; legacy contracts stay intact."""

from types import SimpleNamespace
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import AuthorizationError, ToolError
from langboard.card_workspace.application.dtos import CardBundleResponse
from langboard.mcp_integration import CardLinks
from langboard.mcp_integration.Providers import create_native_domain_provider
from langboard.mcp_integration.Tool import McpTool


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("continuation", [True, False])
async def test_card_links_keep_schema_and_continuation(monkeypatch, modern, continuation):
    async def bundle(project_uid: str, card_uid: str) -> CardBundleResponse:
        payload = {"card_uid": card_uid}
        if continuation:
            payload["continuation"] = {
                "section": "comments",
                "page": {"items": [], "total_count": 0, "next_cursor": None, "limit": 1},
            }
        else:
            payload["card"] = {"core": {"uid": card_uid}, "workflow": {}}
        return CardBundleResponse.model_validate(payload)

    monkeypatch.setattr(CardLinks, "Env", SimpleNamespace(PUBLIC_UI_URL="https://board.example/"))
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"get_card_bundle": {"handler": bundle, "description": "Read"}})
    monkeypatch.setattr(McpTool, "get_tool", lambda name: None)
    server = FastMCP("Native card link fixture")
    server.add_provider(create_native_domain_provider(lambda name, handler: handler, modern_annotations=modern))
    async with Client(server) as client:
        tools = await client.list_tools()
        schema = tools[0].output_schema
        assert ("card_url" in schema["properties"]) is modern
        result = await client.call_tool("get_card_bundle", {"project_uid": "p/one", "card_uid": "c)#two"})
        data = result.structured_content
        assert (data["continuation"] is not None) is continuation
        assert ("card_url" in data) is modern
        if modern:
            assert data["card_url"] == "https://board.example/board/p%2Fone/c%29%23two"
            assert data["card_link_markdown"] == f"[Open card in Langboard]({data['card_url']})"


async def test_denied_card_read_never_produces_links(monkeypatch):
    async def bundle(project_uid: str, card_uid: str) -> CardBundleResponse:
        raise AuthorizationError("Board access denied")

    server = FastMCP("Denied native card link fixture")
    server.tool(CardLinks.with_card_links(bundle), name="get_card_bundle")
    async with Client(server) as client:
        with pytest.raises(ToolError, match="Board access denied"):
            await client.call_tool("get_card_bundle", {"project_uid": "project", "card_uid": "card"})
