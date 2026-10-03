"""Actual MCP dispatch outcomes, including failures after a side effect."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.exceptions import AuthorizationError, ValidationError
from langboard.card_workspace.domain import DescriptionPatchConflict
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("mode", ["success", "after_write", "conflict", "authorization"])
@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
async def test_receipt_does_not_claim_failure_rolled_back_or_change_legacy(monkeypatch, mode, profile):
    effects = []
    name = "update_card_checklist" if profile == "raw" else "patch_card_description"

    def command(value: int) -> dict[str, int]:
        if mode == "authorization":
            raise AuthorizationError("Insufficient permissions")
        if mode == "conflict":
            try:
                raise DescriptionPatchConflict("stale revision")
            except DescriptionPatchConflict as error:
                raise ValidationError("review required") from error
        effects.append(value)
        if mode == "after_write":
            raise RuntimeError("private internal failure details")
        return {"value": value}

    metadata = {"handler": command, "description": "Patch", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda tool_name: metadata if tool_name == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {
            "user_or_bot": object(),
            "tool_group": SimpleNamespace(activated_at=object(), tools=[name]),
        }
    )
    try:
        async with Client(server) as client:
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 3}} if profile == "raw" else {"value": 3},
                raise_on_error=False,
            )
            assert result.is_error is (mode != "success")
            receipt = (result.meta or {}).get("mutation_receipt")
            if profile == "compatibility" or mode == "authorization":
                assert receipt is None
            else:
                assert len(receipt["request_id"]) == 32
                assert receipt["tool"] == name
                assert (
                    receipt["outcome"]
                    == {"success": "applied", "after_write": "unknown", "conflict": "not_applied"}[mode]
                )
                assert receipt["retryable"] is False
                assert receipt["revision_conflict"] is (mode == "conflict")
                assert "private internal failure" not in str(result.content)
            if mode == "success":
                assert result.structured_content == {"value": 3}
            assert effects == ([3] if mode in {"success", "after_write"} else [])
    finally:
        mcp_auth_context.reset(token)
