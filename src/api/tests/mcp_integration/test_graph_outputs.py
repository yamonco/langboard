"""Graph output schemas preserve native result and post-save uncertainty."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.domain import CardGraphNewCard
from langboard.mcp_integration.GraphOutputs import GraphPatchOutput
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import CardMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import Card, CardRelationship
from pydantic import TypeAdapter


def native_graph():
    card = Card(id=123, project_id=456, project_column_id=789, title="Child")
    edge = CardRelationship(id=222, relationship_type_id=333, card_id_parent=444, card_id_child=123)
    return {
        "anchor_card_uid": "anchor",
        "created_cards": [card.board_api_response(0, [], [], [])],
        "created_relationships": [edge.api_response()],
        "removed_relationship_uids": ["removed"],
    }


def test_native_graph_card_and_relationship_models_roundtrip():
    expected = native_graph()
    assert GraphPatchOutput.model_validate(expected).model_dump(mode="json") == TypeAdapter(dict).dump_python(
        expected, mode="json"
    )


@pytest.mark.parametrize("profile", ["agent", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_actual_graph_handler_preserves_domain_call_and_unknown_receipt(monkeypatch, profile, malformed):
    payload = native_graph()
    effects = []

    def apply(*args):
        effects.append(args)
        assert args[3] == [("new:child", "Child", None)]
        if malformed:
            payload["created_relationships"][0]["child_card_uid"] = 1
        return payload

    service = SimpleNamespace(card_relationship=SimpleNamespace(apply_graph_patch=apply))

    def handler(title: str) -> dict:
        return CardMcp.apply_card_graph_patch(
            "board", "anchor", [CardGraphNewCard("new:child", title)], [], ["removed"], object(), service
        )

    name = "apply_card_graph_patch"
    metadata = {"handler": handler, "description": "Patch graph", "exclude": [], "accessible_type": "all"}
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
            if profile == "agent":
                schema = (await client.list_tools())[0].output_schema
                assert (
                    schema["properties"]["created_relationships"]["items"]["properties"]["child_card_uid"]["type"]
                    == "string"
                )
            result = await client.call_tool(name, {"title": " Child "}, raise_on_error=False)
            assert len(effects) == 1
            if malformed and profile == "agent":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                assert result.structured_content == TypeAdapter(dict).dump_python(payload, mode="json")
    finally:
        mcp_auth_context.reset(token)
