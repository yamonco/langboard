"""Notification contracts preserve native pages and never acknowledge reads."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.NotificationOutputs import UnreadNotificationsOutput
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_tools import UserMcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.models.UserNotification import NotificationType, UserNotification
from pydantic import TypeAdapter, ValidationError


def notification_payload(kind, bot=False):
    native = UserNotification(
        id=123,
        notifier_type="bot" if bot else "user",
        notifier_id=456,
        receiver_id=789,
        notification_type=kind,
        message_vars={"text": "한글", "items": [True, 2, None]},
    )
    actor = (
        Bot(
            id=456,
            name="Sender",
            bot_uname="sender",
            app_api_token="fixture",
            platform="default",
            platform_running_type="default",
        )
        if bot
        else User(id=456, firstname="Sender", lastname="User", email="fixture@example.invalid", password="fixture")
    )
    return {
        **native.api_response(),
        "notifier_bot" if bot else "notifier_user": actor.notification_data(),
        "records": {"card": {"uid": "card", "title": "업무"}, "user": actor.notification_data()},
    }


@pytest.mark.parametrize("kind", list(NotificationType))
@pytest.mark.parametrize("bot", [False, True])
def test_native_notification_variants_preserve_json_and_actor_omissions(kind, bot):
    payload = {"notifications": [notification_payload(kind, bot)], "returned_count": 1}
    actual = UnreadNotificationsOutput.model_validate(payload).model_dump(mode="json")
    assert actual == TypeAdapter(dict).dump_python(payload, mode="json")


@pytest.mark.parametrize("problem", ["count", "both", "missing", "read_at", "type", "extra"])
def test_malformed_notification_envelopes_are_rejected(problem):
    item = notification_payload(NotificationType.MentionedInCard)
    payload = {"notifications": [item], "returned_count": 1}
    if problem == "count":
        payload["returned_count"] = 0
    elif problem == "both":
        item["notifier_bot"] = {"uid": "bot"}
    elif problem == "missing":
        del item["notifier_user"]
    elif problem == "read_at":
        item["read_at"] = 12
    elif problem == "type":
        item["type"] = "invented"
    else:
        item["receiver_id"] = 789
    with pytest.raises(ValidationError):
        UnreadNotificationsOutput.model_validate(payload)


@pytest.mark.parametrize("profile", ["agent", "raw", "compatibility"])
async def test_notification_transport_preserves_native_unread_query(monkeypatch, profile):
    item = notification_payload(NotificationType.AssignedToCard)
    calls = []

    def page(*args, **kwargs):
        calls.append((args, kwargs))
        return [item], True, 100

    service = SimpleNamespace(notification=SimpleNamespace(get_api_list=page))
    actor = object()

    def handler(page: int = 1, limit: int = 20) -> dict:
        return UserMcp.get_unread_notifications(actor, service, page=page, limit=limit)

    name = "get_unread_notifications"
    metadata = {"handler": handler, "description": "Unread", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": actor, "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            # Raw contains only primitive tools; this canonical read stays in Agent.
            if profile == "raw":
                assert name not in [tool.name for tool in await client.list_tools()]
                return
            schema = (await client.list_tools())[0].output_schema
            if profile == "agent":
                assert schema["properties"]["returned_count"]["maximum"] == 50
                assert schema["additionalProperties"] is False
            result = await client.call_tool(name, {"page": 2, "limit": 1})
            expected = {"notifications": [item], "returned_count": 1}
            assert result.structured_content == TypeAdapter(dict).dump_python(expected, mode="json")
            assert calls == [((actor, "all", 2, 1), {"unread_only": True, "authorized_projects_only": True})]
            assert "mutation_receipt" not in (result.meta or {})
    finally:
        mcp_auth_context.reset(token)
