from __future__ import annotations
from hashlib import sha256
from json import dumps as json_dumps
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ....core.types import SnowflakeID
from ....core.utils.Converter import convert_python_data
from .WebhookModel import WORK_EVENT_NAME, WebhookModel


ACTION_REQUIRED_NOTIFICATION_TYPES = frozenset(
    {
        "assigned_to_card",
        "mentioned_in_card",
        "mentioned_in_comment",
        "mentioned_in_wiki",
        "notified_from_checklist",
        "project_invited",
        "scheduled_rule",
    }
)

_SCOPE_KEYS = {
    "project": "project_uid",
    "project_column": "project_column_uid",
    "card": "card_uid",
    "project_wiki": "wiki_uid",
    "checklist": "checklist_uid",
    "checkitem": "checkitem_uid",
    "project_invitation": "project_invitation_uid",
}


class WorkEventPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "bot"]
    uid: str = Field(min_length=1, max_length=64)


class WorkEventData(BaseModel):
    """Reference-only action event; downstream consumers re-read authorized content."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=100)
    actor: WorkEventPrincipal
    recipient: WorkEventPrincipal
    scope: dict[str, str]
    notification_uid: str = Field(min_length=1, max_length=64)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_id: str = Field(min_length=1, max_length=64)
    priority: Literal["action_required"] = "action_required"

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, scope: dict[str, str]) -> dict[str, str]:
        allowed = frozenset(_SCOPE_KEYS.values())
        if "project_uid" not in scope:
            raise ValueError("work event scope requires project_uid")
        if unknown := set(scope) - allowed:
            raise ValueError(f"work event scope contains unknown fields: {', '.join(sorted(unknown))}")
        if any(not isinstance(value, str) or not value for value in scope.values()):
            raise ValueError("work event scope identifiers must be non-empty strings")
        return scope


def build_notification_work_event(notification: Any) -> WebhookModel | None:
    """Create one stable event from the same immutable model used for Web notifications."""

    event_type = getattr(getattr(notification, "notification_type", None), "value", None)
    if event_type not in ACTION_REQUIRED_NOTIFICATION_TYPES:
        return None

    notification_uid = notification.get_uid()
    event_id = str(uuid5(NAMESPACE_URL, f"langboard:user-notification:{notification_uid}"))
    scope = {
        key: _short_uid(record_id)
        for table_name, record_id in notification.record_list
        if (key := _SCOPE_KEYS.get(table_name)) is not None
    }
    fingerprint_payload = {
        "event_type": event_type,
        "actor": {"kind": notification.notifier_type, "uid": _short_uid(notification.notifier_id)},
        "recipient": {"kind": "user", "uid": _short_uid(notification.receiver_id)},
        "scope": scope,
        "notification_uid": notification_uid,
        "message_vars": convert_python_data(notification.message_vars, recursive=True),
    }
    payload_hash = sha256(
        json_dumps(fingerprint_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    data = WorkEventData(
        event_type=event_type,
        actor=WorkEventPrincipal(
            kind=notification.notifier_type,
            uid=_short_uid(notification.notifier_id),
        ),
        recipient=WorkEventPrincipal(kind="user", uid=_short_uid(notification.receiver_id)),
        scope=scope,
        notification_uid=notification_uid,
        payload_hash=payload_hash,
        correlation_id=event_id,
    )
    return WebhookModel(
        event_id=event_id,
        occurred_at=notification.created_at.isoformat(),
        event=WORK_EVENT_NAME,
        data=data.model_dump(),
    )


def _short_uid(value: Any) -> str:
    if isinstance(value, SnowflakeID):
        return value.to_short_code()
    return SnowflakeID(int(value)).to_short_code()
