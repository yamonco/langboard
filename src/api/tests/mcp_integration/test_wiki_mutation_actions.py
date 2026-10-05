"""Native wiki mutations keep revision gates and canonical authorization."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langboard.mcp_integration.Providers import create_native_agent_provider
from langboard.mcp_integration.Receipts import MutationReceiptMiddleware
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools.WikiActionsMcp import WIKI_ACTION_COMMANDS, WikiMutation, update_wiki
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.exceptions.WikiContentConflict import WikiContentConflict
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {"action": "append", "text": "  한글\n"},
        {"action": "patch", "edits": [{"old_text": "  원문", "new_text": "  수정"}]},
        {"action": "replace", "content": ""},
        {"action": "delete"},
    ],
)
async def test_native_wiki_mutation_dispatch_receipt_and_conflict(monkeypatch, denied, change):
    original = McpTool.get_tool("update_wiki")
    calls = []
    conflict = False
    output = {"deleted": True} if change["action"] == "delete" else {"wiki_uid": "wiki", "revision": "b" * 64}

    def command(**kwargs):
        calls.append(kwargs)
        if conflict:
            raise WikiContentConflict("stale reviewed revision")
        return output

    metadata = {"handler": command, "exclude": [], "accessible_type": "user"}
    target = WIKI_ACTION_COMMANDS[change["action"]]
    monkeypatch.setattr(McpTool, "get_tools", lambda: {"update_wiki": original})
    monkeypatch.setattr(
        McpTool, "get_tool", lambda name: original if name == "update_wiki" else metadata if name == target else None
    )
    monkeypatch.setattr(McpServer, "_validate_auth", lambda actor, name: actor == "fixture")
    monkeypatch.setattr(
        McpServer, "_validate_role", lambda actor, handler, **kwargs: not denied or handler is update_wiki
    )
    server = FastMCP("Native wiki mutation fixture", middleware=[MutationReceiptMiddleware()])
    server.add_provider(create_native_agent_provider(McpServer._wrap_tool))
    token = mcp_auth_context.set({"transport": "oauth", "user_or_bot": "fixture"})
    try:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert not tools["update_wiki"].annotations.read_only_hint
            assert len(tools["update_wiki"].input_schema["properties"]["change"]["oneOf"]) == 4
            args = {"project_uid": "project", "wiki_uid": "wiki", "expected_revision": "a" * 64, "change": change}
            if denied:
                with pytest.raises(ToolError, match="Insufficient permissions"):
                    await client.call_tool("update_wiki", args)
                assert not calls
            else:
                result = await client.call_tool("update_wiki", args)
                assert result.structured_content == output
                assert result.meta["mutation_receipt"]["outcome"] == "applied"
                assert calls[-1] == {
                    "project_uid": "project",
                    "wiki_uid": "wiki",
                    "expected_revision": "a" * 64,
                    **{k: v for k, v in change.items() if k != "action"},
                }
                conflict = True
                result = await client.call_tool("update_wiki", args, raise_on_error=False)
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "not_applied"
                assert result.meta["mutation_receipt"]["revision_conflict"] is True
                assert result.meta["mutation_receipt"]["retryable"] is False
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "change",
    [
        {"action": "append"},
        {"action": "append", "text": "x", "content": "y"},
        {"action": "patch", "edits": []},
        {"action": "patch", "edits": [{"old_text": "", "new_text": "x"}]},
        {"action": "replace"},
        {"action": "delete", "content": ""},
    ],
)
def test_invalid_wiki_changes_rejected(change):
    with pytest.raises(ValidationError):
        TypeAdapter(WikiMutation).validate_python(change)
