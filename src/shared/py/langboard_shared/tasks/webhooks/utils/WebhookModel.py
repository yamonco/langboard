from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
from ....ai.BotDefaultTrigger import BotDefaultTrigger
from ....domain.models.bases.BotTriggerCondition import BotTriggerCondition


WEBHOOK_EVENT_NAMES = frozenset(trigger.value for trigger in (*BotTriggerCondition, *BotDefaultTrigger))


def validate_webhook_events(events: list[str] | None) -> list[str] | None:
    """Validate an optional webhook event allowlist against emitted events."""

    if events is None:
        return None
    if not events:
        raise ValueError("Webhook events must contain at least one event name")
    if len(events) != len(set(events)):
        raise ValueError("Webhook events must be unique")

    invalid_events = sorted(set(events) - WEBHOOK_EVENT_NAMES)
    if invalid_events:
        raise ValueError(f"Unknown webhook events: {', '.join(invalid_events)}")
    return events


class WebhookModel(BaseModel):
    """Stable at-least-once webhook event envelope."""

    schema_version: Literal["1"] = "1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: str
    data: dict[str, Any]

    @field_validator("event")
    @classmethod
    def validate_event(cls, event: str) -> str:
        """Reject event envelopes that are not emitted by Langboard."""

        if event not in WEBHOOK_EVENT_NAMES:
            raise ValueError(f"Unknown webhook event: {event}")
        return event
