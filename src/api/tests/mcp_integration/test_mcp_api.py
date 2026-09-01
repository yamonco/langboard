"""MCP REST compatibility adapter tests."""

from types import SimpleNamespace
import pytest
from langboard.mcp_integration import Server
from langboard.routes.mcp.McpApi import serialize_mcp_result
from pydantic import BaseModel


def test_typed_results_are_recursively_dumped_as_json() -> None:
    """Nested typed outputs remain structured JSON in the REST compatibility facade."""

    class Card(BaseModel):
        uid: str

    class Result(BaseModel):
        card: Card

    assert serialize_mcp_result({"page": [Result(card=Card(uid="c1"))]}) == {"page": [{"card": {"uid": "c1"}}]}


def test_accessible_type_rejects_wrong_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared native wrapper keeps user-only and bot-only tools isolated."""

    class FakeUser:
        pass

    class FakeBot:
        pass

    monkeypatch.setattr(Server, "User", FakeUser)
    monkeypatch.setattr(Server, "Bot", FakeBot)
    monkeypatch.setattr(
        Server.McpTool,
        "get_tool",
        lambda name: {"accessible_type": "bot"} if name == "bot_tool" else None,
    )

    assert Server.McpServer._validate_auth(FakeBot(), "bot_tool") is True
    assert Server.McpServer._validate_auth(FakeUser(), "bot_tool") is False
    assert Server.McpServer._validate_auth(SimpleNamespace(), "bot_tool") is False
