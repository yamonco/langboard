"""Native bot receipts retain scope, dates and operation meaning."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.BotOutputs import BOT_OUTPUTS
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import BotSchedule, CardBotSchedule, ProjectBotSchedule, ProjectColumnBotSchedule
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.domain.models.BotSchedule import BotScheduleStatus
from langboard_shared.domain.services.factory.BotService import BotService
from pydantic import TypeAdapter


def native_schedule(operation, model=CardBotSchedule, field="card_id"):
    now = SafeDateTime.now()
    schedule = BotSchedule(
        id=123, bot_id=456, status=BotScheduleStatus.Started, interval_str="0 9 * * *", created_at=now
    )
    association = model(id=789, bot_schedule_id=123, **{field: 222})
    return BotService._schedule_receipt(
        operation,
        SimpleNamespace(get_uid=lambda: "bot"),
        schedule,
        association,
        field.removesuffix("_id"),
        "target",
        changes={"status": "pending", "start_at": now, "end_at": None} if operation == "updated" else None,
    )


@pytest.mark.parametrize(
    "name,operation",
    [("schedule_bot_cron", "created"), ("reschedule_bot_cron", "updated"), ("unschedule_bot_cron", "deleted")],
)
@pytest.mark.parametrize(
    "model,field",
    [(CardBotSchedule, "card_id"), (ProjectBotSchedule, "project_id"), (ProjectColumnBotSchedule, "project_column_id")],
)
def test_native_schedule_receipt_preserves_scope_and_partial_changes(name, operation, model, field):
    expected = native_schedule(operation, model, field)
    actual = BOT_OUTPUTS[name].model_validate(expected).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(expected, mode="json")
    assert set(actual["changes"]) == ({"status", "start_at", "end_at"} if operation == "updated" else set())


@pytest.mark.parametrize(
    "name,operation", [("upsert_bot_hook", "upserted"), ("update_bot_hook", "updated"), ("delete_bot_hook", "deleted")]
)
def test_native_hook_receipt_retains_events_and_inactive_state(name, operation):
    scope = SimpleNamespace(get_uid=lambda: "hook", conditions=[BotTriggerCondition.CardMoved], is_frozen=True)
    expected = {
        "operation": operation,
        "hook": BotService._hook_response(SimpleNamespace(get_uid=lambda: "bot"), scope, "card", "target"),
    }
    assert BOT_OUTPUTS[name].model_validate(expected).model_dump(mode="json") == expected


@pytest.mark.parametrize("profile", ["raw", "compatibility"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_schedule_output_failure_after_execution_is_unknown(monkeypatch, profile, malformed):
    name = "reschedule_bot_cron"
    payload = native_schedule("updated")
    if malformed:
        payload["schedule"]["status"] = "approved"
    effects = []

    def handler(value: int) -> dict:
        effects.append(value)
        return payload

    metadata = {"handler": handler, "description": "Update schedule", "exclude": [], "accessible_type": "all"}
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
                assert schema["properties"]["operation"]["const"] == "updated"
                assert len(schema["properties"]["schedule"]["anyOf"]) == 3
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 1}} if profile == "raw" else {"value": 1},
                raise_on_error=False,
            )
            assert effects == [1]
            if profile == "raw" and malformed:
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                assert result.structured_content == TypeAdapter(dict).dump_python(payload, mode="json")
                if profile == "compatibility":
                    assert not (result.meta or {}).get("mutation_receipt")
    finally:
        mcp_auth_context.reset(token)
