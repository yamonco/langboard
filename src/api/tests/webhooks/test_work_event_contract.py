from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
import pytest
from langboard_shared.core.publisher import NotificationPublisher
from langboard_shared.core.types import SnowflakeID
from langboard_shared.tasks.webhooks import WebhookTask
from langboard_shared.tasks.webhooks.utils import WorkEventData, build_notification_work_event


def _notification(event_type: str, *, message: str = "review this") -> SimpleNamespace:
    notification_id = SnowflakeID(8_001)
    return SimpleNamespace(
        notification_type=SimpleNamespace(value=event_type),
        notifier_type="user",
        notifier_id=SnowflakeID(8_002),
        receiver_id=SnowflakeID(8_006),
        record_list=[
            ("project", SnowflakeID(8_003)),
            ("project_column", SnowflakeID(8_004)),
            ("card", SnowflakeID(8_005)),
        ],
        message_vars={"line": message},
        created_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
        get_uid=notification_id.to_short_code,
    )


def test_action_required_notification_builds_stable_reference_only_work_event() -> None:
    notification = _notification("mentioned_in_card")

    first = build_notification_work_event(notification)
    second = build_notification_work_event(notification)

    assert first is not None and second is not None
    assert first.event == "work_event"
    assert first.event_id == second.event_id
    assert first.occurred_at == "2026-09-10T08:00:00+00:00"
    assert first.data == second.data
    data = WorkEventData.model_validate(first.data)
    assert data.event_type == "mentioned_in_card"
    assert data.actor.kind == "user"
    assert data.recipient.kind == "user"
    assert set(data.scope) == {"project_uid", "project_column_uid", "card_uid"}
    assert data.correlation_id == first.event_id
    assert data.priority == "action_required"
    assert "review this" not in str(first.data)


def test_payload_hash_changes_without_exposing_notification_content() -> None:
    first = build_notification_work_event(_notification("assigned_to_card", message="first"))
    second = build_notification_work_event(_notification("assigned_to_card", message="second"))

    assert first is not None and second is not None
    assert first.data["payload_hash"] != second.data["payload_hash"]
    assert "first" not in str(first.data)
    assert "second" not in str(second.data)


def test_low_value_reaction_does_not_create_work_event() -> None:
    assert build_notification_work_event(_notification("reacted_to_comment")) is None


def test_notification_publisher_uses_the_same_notification_for_web_and_work_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued_notifications: list[object] = []
    queued_work_events: list[object] = []
    publisher_module = import_module("langboard_shared.core.publisher.NotificationPublisher")
    monkeypatch.setattr(publisher_module.DispatcherQueue, "put", queued_notifications.append)
    monkeypatch.setattr(WebhookTask, "webhook_task", queued_work_events.append)
    model = SimpleNamespace(
        notification=_notification("notified_from_checklist"),
        target_user=SimpleNamespace(get_uid=SnowflakeID(9_999).to_short_code),
        model_dump=lambda: {"notification": "same-source"},
    )

    NotificationPublisher.put_dispather(model)

    assert len(queued_notifications) == 1
    assert queued_notifications[0].data == {"notification": "same-source"}
    assert len(queued_work_events) == 1
    assert queued_work_events[0].data["notification_uid"] == model.notification.get_uid()
    assert queued_work_events[0].data["recipient"]["uid"] == SnowflakeID(8_006).to_short_code()


@pytest.mark.asyncio
async def test_work_event_delivery_requires_explicit_endpoint_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def setting(uid: str, events: list[str] | None) -> SimpleNamespace:
        return SimpleNamespace(events=events, get_uid=lambda: uid)

    scheduled: list[str] = []
    monkeypatch.setattr(
        WebhookTask,
        "_get_webhook_settings",
        lambda: [
            setting("legacy-all", None),
            setting("explicit", ["work_event"]),
            setting("other", ["card_created"]),
        ],
    )
    monkeypatch.setattr(WebhookTask, "webhook_delivery_task", lambda _model, uid: scheduled.append(uid))
    model = build_notification_work_event(_notification("scheduled_rule"))

    assert model is not None
    await WebhookTask.run_webhook(model)

    assert scheduled == ["explicit"]


def test_work_event_schema_fields_are_not_available_to_other_events() -> None:
    schema_module = import_module("langboard.routes.schemas.WebhookSchemaApi")
    untrusted = {
        "project_uid": "string",
        "actor": {"secret": "string"},
        "payload_hash": "string",
    }

    assert schema_module._minimal_event_schema(untrusted, event="card_created") == {"project_uid": "string"}


def test_work_event_scope_rejects_unknown_or_unscoped_identifiers() -> None:
    common = {
        "event_type": "mentioned_in_card",
        "actor": {"kind": "user", "uid": "actor"},
        "recipient": {"kind": "user", "uid": "recipient"},
        "notification_uid": "notification",
        "payload_hash": "0" * 64,
        "correlation_id": "correlation",
    }

    with pytest.raises(ValueError, match="requires project_uid"):
        WorkEventData.model_validate({**common, "scope": {"card_uid": "card"}})
    with pytest.raises(ValueError, match="unknown fields"):
        WorkEventData.model_validate(
            {**common, "scope": {"project_uid": "project", "email": "private@example.invalid"}}
        )
