"""Telemetry reports execution evidence without copying any caller payload."""

import json
import logging
from types import SimpleNamespace
import pytest
from fastmcp.exceptions import AuthorizationError
from fastmcp.tools import ToolResult
from langboard.mcp_integration.Telemetry import ToolTelemetryMiddleware
from langboard.mcp_integration.Tool import McpTool


@pytest.mark.parametrize("raw", [True, False])
@pytest.mark.parametrize("outcome", ["applied", "not_applied", "unknown", "success", "error", "denied"])
async def test_safe_telemetry_keeps_receipt_identity_and_does_not_modify_results(monkeypatch, caplog, raw, outcome):
    monkeypatch.setattr(
        McpTool, "get_tool", lambda name: {"handler": object()} if name == "patch_card_description" else None
    )
    caplog.set_level(logging.INFO, logger="langboard.mcp.telemetry")
    receipt = {"request_id": "a" * 32, "outcome": outcome} if outcome in {"applied", "not_applied", "unknown"} else None
    result = ToolResult(
        content="PRIVATE_RESPONSE", is_error=outcome == "error", meta={"mutation_receipt": receipt} if receipt else {}
    )
    context = SimpleNamespace(
        message=SimpleNamespace(
            name="call_raw_tool" if raw else "patch_card_description",
            arguments={
                "name": "patch_card_description",
                "arguments": {"content": "PRIVATE_BODY", "token": "PRIVATE_TOKEN"},
            },
        )
    )

    async def next_call(value):
        assert value is context
        if outcome == "denied":
            raise AuthorizationError("PRIVATE_ERROR")
        return result

    if outcome == "denied":
        with pytest.raises(AuthorizationError):
            await ToolTelemetryMiddleware().on_call_tool(context, next_call)
    else:
        assert await ToolTelemetryMiddleware().on_call_tool(context, next_call) is result
    records = [r for r in caplog.records if r.name == "langboard.mcp.telemetry"]
    assert len(records) == 1
    payload = json.loads(records[0].message)
    assert set(payload) == {"event", "request_id", "tool", "duration_ms", "outcome"}
    assert payload["tool"] == "patch_card_description" and payload["outcome"] == outcome
    assert payload["duration_ms"] >= 0
    if receipt:
        assert payload["request_id"] == receipt["request_id"]
    assert "PRIVATE_" not in records[0].message


async def test_unrecognized_name_and_exception_details_are_not_logged(monkeypatch, caplog):
    monkeypatch.setattr(McpTool, "get_tool", lambda _: None)
    caplog.set_level(logging.INFO, logger="langboard.mcp.telemetry")
    context = SimpleNamespace(message=SimpleNamespace(name="call_raw_tool", arguments={"name": "PRIVATE_TOKEN"}))

    async def fail(_):
        raise RuntimeError("PRIVATE_ERROR")

    with pytest.raises(RuntimeError):
        await ToolTelemetryMiddleware().on_call_tool(context, fail)
    record = json.loads(caplog.records[-1].message)
    assert record["tool"] == "unknown" and record["outcome"] == "error"
    assert "PRIVATE_" not in caplog.records[-1].message


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
async def test_native_transport_record_matches_mutation_receipt(monkeypatch, caplog, profile):
    from fastmcp import Client
    from langboard.mcp_integration.Server import McpServer
    from langboard.middlewares.McpAuthMiddleware import mcp_auth_context

    name = "mark_all_notifications_read" if profile == "raw" else "mark_notification_read"

    def handler(notification_uid: str) -> dict:
        return {"read": True}

    metadata = {"handler": handler, "description": "Read", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    caplog.set_level(logging.INFO, logger="langboard.mcp.telemetry")
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            arguments = {"notification_uid": "PRIVATE_UID"}
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": arguments} if profile == "raw" else arguments,
            )
            assert result.structured_content == {"read": True}
            records = [json.loads(r.message) for r in caplog.records if r.name == "langboard.mcp.telemetry"]
            assert len(records) == 1
            record = records[0]
            assert record["tool"] == name
            assert "PRIVATE_" not in json.dumps(record)
            if profile == "compatibility":
                assert record["outcome"] == "success"
                assert "mutation_receipt" not in (result.meta or {})
            else:
                receipt = result.meta["mutation_receipt"]
                assert record["request_id"] == receipt["request_id"]
                assert record["outcome"] == receipt["outcome"] == "applied"
    finally:
        mcp_auth_context.reset(token)
