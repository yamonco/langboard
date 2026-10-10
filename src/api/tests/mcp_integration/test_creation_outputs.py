"""Creation result contracts preserve native state and explicit destinations."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.application.projections import public_card_summary
from langboard.mcp_integration.CreationOutputs import CREATION_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import CardMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.db import EditorContentModel
from langboard_shared.domain.models import Card, User
from langboard_shared.domain.services.factory.CardService import CardService
from pydantic import TypeAdapter


def native_card(empty=False):
    card = Card(
        id=123,
        project_id=456,
        project_column_id=789,
        title="한글",
        description=EditorContentModel(content="" if empty else "Body"),
        last_change_seq=7,
    )
    creator = CardService._card_creator_projection(
        object(),
        card,
        User(id=222, email="fixture@example.invalid", password="fixture", firstname="User", lastname="Name"),
    )
    return card, card.board_api_response(0, ["assignee"], [], [], creator=creator, is_check_card=empty)


@pytest.mark.parametrize("empty", [False, True])
def test_real_card_result_keeps_creator_body_and_completion_flags(empty):
    _, expected = native_card(empty)
    actual = CREATION_OUTPUTS["create_card"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert actual["creator"]["type"] == "user"
    assert actual["is_check_card"] is empty
    assert actual["last_change_seq"] == 7


def test_actual_cardification_handler_keeps_public_summary_and_source(monkeypatch):
    card, full = native_card()
    project = SimpleNamespace(id=456)
    item = SimpleNamespace(checklist_id=1, cardified_id=None)
    writes = []
    service = SimpleNamespace(
        checkitem=SimpleNamespace(
            get_by_id_like=lambda _: item,
            cardify=lambda *args: writes.append(args) or setattr(item, "cardified_id", card.id) or True,
        ),
        checklist=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(card_id=card.id)),
        project_column=SimpleNamespace(
            get_by_id_like=lambda _: SimpleNamespace(project_id=project.id, is_archive=False)
        ),
        card=SimpleNamespace(get_by_id_like=lambda _: card),
    )
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *args: (project, card))
    expected = CardMcp.cardify_card_checkitem("board", "card", "item", "column", object(), service)
    actual = CREATION_OUTPUTS["cardify_card_checkitem"].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert actual["source_checkitem_uid"] == "item"
    assert "description" not in actual["card"]
    assert "project_column_uid" in actual["card"]
    assert len(writes) == 1
    assert CREATION_OUTPUTS["cardify_card_checkitem"].model_validate(
        {"card": public_card_summary(full), "source_checkitem_uid": "item"}
    )


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_creation_native_handler_and_postsave_unknown(monkeypatch, profile, malformed):
    name = "create_card" if profile == "agent" else "create_card_in_leftmost_column"
    card, native = native_card()
    effects = []

    def create(*args):
        effects.append(args)
        assert args[2] == "left" and args[5] == ["assignee"]
        if malformed:
            native["title"] = 1
        return card, native

    service = SimpleNamespace(
        project=SimpleNamespace(
            get_by_id_like=lambda _: object(), get_api_assigned_user_list=lambda *args, **kwargs: [{"uid": "assignee"}]
        ),
        project_column=SimpleNamespace(
            get_api_list_by_project=lambda _: [
                {"uid": "archive", "name": "Archive", "order": 0, "is_archive": True},
                {"uid": "right", "name": "Right", "order": 2, "is_archive": False},
                {"uid": "left", "name": "Left", "order": 1, "is_archive": False},
            ]
        ),
        card=SimpleNamespace(create=create),
    )

    def handler(title: str) -> dict:
        if profile == "agent":
            return CardMcp.create_card("board", "leftmost", title, "Body", ["assignee"], object(), service)
        return CardMcp.create_card_in_leftmost_column("board", title, object(), service, "Body", ["assignee"])

    metadata = {"handler": handler, "description": "Create", "exclude": [], "accessible_type": "all"}
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
                assert json.loads(search.content[0].text)[0]["outputSchema"]["properties"]["card"]["properties"][
                    "creator"
                ]
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"title": "Card"}} if profile == "raw" else {"title": "Card"},
                raise_on_error=False,
            )
            assert len(effects) == 1
            if malformed and profile != "compatibility":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                expected = native if profile == "agent" else {"card": native, "column": {"uid": "left", "name": "Left"}}
                assert result.structured_content == TypeAdapter(dict).dump_python(expected, mode="json")
    finally:
        mcp_auth_context.reset(token)
