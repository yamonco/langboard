"""Output validation must never imply rollback of an executed command."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.Outputs import COMMAND_OUTPUTS, with_typed_output
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_native_output_schema_payload_and_post_write_failure(monkeypatch, profile, malformed):
    name = "mark_all_notifications_read" if profile == "raw" else "mark_notification_read"
    effects = []
    payload = {"read": "yes"} if malformed else {"read": True}

    def command(notification_uid: str) -> dict[str, bool]:
        effects.append(notification_uid)
        return payload

    metadata = {"handler": command, "description": "Read notification", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda tool_name: metadata if tool_name == name else None)
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
                schema = json.loads(search.content[0].text)[0]["outputSchema"]
            else:
                schema = (await client.list_tools())[0].output_schema
            if profile != "compatibility":
                assert schema["properties"]["read"]["const"] is True
                assert schema["additionalProperties"] is False
            arguments = {"notification_uid": "owned"}
            if malformed and profile == "compatibility":
                with pytest.raises(RuntimeError, match="Invalid structured content"):
                    await client.call_tool(name, arguments)
                assert effects == ["owned"]
                return
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": arguments} if profile == "raw" else arguments,
                raise_on_error=False,
            )
            assert effects == ["owned"]
            if malformed and profile != "compatibility":
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
                assert "yes" not in str(result.content)
            else:
                assert not result.is_error
                assert result.structured_content == payload
                if profile == "compatibility":
                    assert "mutation_receipt" not in (result.meta or {})
    finally:
        mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "name,payload",
    [
        (
            "patch_card_description",
            {"changed": True, "description_revision": "a" * 64, "description_chars": 0, "applied_edits": 1},
        ),
        ("replace_card_description", {"changed": True, "description_revision": "a" * 64, "description_chars": 0}),
        ("assign_card_to_me", {"card_uid": "card", "assigned_user_uid": "actor", "changed": False}),
        ("mark_notification_read", {"read": True}),
        ("mark_all_notifications_read", {"read": True}),
    ],
)
async def test_reviewed_outputs_preserve_fields_and_reject_drift(name, payload):
    from pydantic import ValidationError

    async def handler():
        return payload

    result = await with_typed_output(name, handler)()
    assert result.model_dump() == payload
    with pytest.raises(ValidationError):
        COMMAND_OUTPUTS[name].model_validate({**payload, "unexpected": "private"})
    with pytest.raises(ValidationError):
        COMMAND_OUTPUTS[name].model_validate({})
