"""Independent clients use native comment actions with canonical ACL dispatch."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import create_agent_core_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.CommentActionsMcp import COMMENT_ACTION_COMMANDS, CommentChange
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"action": "add", "content": " 한글 댓글 "}, {"content": "한글 댓글"}),
        (
            {"action": "edit", "comment_uid": "comment", "content": "수정"},
            {"comment_uid": "comment", "content": "수정"},
        ),
        ({"action": "delete", "comment_uid": "comment"}, {"comment_uid": "comment"}),
        (
            {"action": "react", "comment_uid": "comment", "reaction": "eyes"},
            {"comment_uid": "comment", "reaction": "eyes"},
        ),
    ],
)
@pytest.mark.parametrize("denied", [False, True])
async def test_comment_facade_dispatches_authorized_command(monkeypatch, change, expected, denied):
    original = McpTool.get_tool("change_card_comment")
    calls = []
    output = {
        "comment": {
            "uid": "comment",
            "content": "수정",
            "content_format": "text",
            "content_total_chars": 2,
            "content_truncated": False,
        }
    }
    if change["action"] == "delete":
        output = {"deleted": True}
    elif change["action"] == "react":
        output = {"is_reacted": False}

    def command(**kwargs):
        calls.append(kwargs)
        return output

    metadata = {"handler": command, "exclude": [], "accessible_type": "all"}
    target = COMMENT_ACTION_COMMANDS[change["action"]]
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"change_card_comment": original})
    monkeypatch.setattr(
        McpTool,
        "get_tool",
        lambda name: original if name == "change_card_comment" else metadata if name == target else None,
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture-user")
    monkeypatch.setattr(
        McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied or handler is original["handler"]
    )
    server = FastMCP("Native comment action fixture")
    server.add_provider(create_agent_core_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture-user"})
    try:
        async with Client(server) as client:
            tool = (await client.list_tools())[0]
            assert tool.name == "change_card_comment"
            assert len(tool.input_schema["properties"]["change"]["oneOf"]) == 4
            assert tool.output_schema
            args = {"project_uid": "project", "card_uid": "card", "change": change}
            if denied:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool("change_card_comment", args)
                assert calls == []
            else:
                result = await client.call_tool("change_card_comment", args)
                assert result.structured_content == output
                assert calls == [{"project_uid": "project", "card_uid": "card", **expected}]
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "change",
    [
        {"action": "add", "content": " "},
        {"action": "add", "content": "text", "comment_uid": "unexpected"},
        {"action": "edit", "content": "text"},
        {"action": "delete", "comment_uid": ""},
        {"action": "react", "comment_uid": "comment", "reaction": "approved"},
        {"action": "delete", "comment_uid": "comment", "content": "text"},
    ],
)
def test_invalid_comment_actions_never_dispatch(change):
    with pytest.raises(ValidationError):
        TypeAdapter(CommentChange).validate_python(change)
