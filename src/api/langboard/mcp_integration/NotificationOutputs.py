"""Typed notification envelopes preserve native dynamic template records."""

from datetime import datetime
from typing import Literal
from pydantic import Field, JsonValue, TypeAdapter, field_validator, model_validator
from .Outputs import CommandOutput
from .WorkOutputs import ProjectionOutput


class NotificationOutput(ProjectionOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    type: Literal[
        "project_invited",
        "mentioned_in_card",
        "mentioned_in_comment",
        "mentioned_in_wiki",
        "assigned_to_card",
        "reacted_to_comment",
        "notified_from_checklist",
        "scheduled_rule",
    ]
    read_at: datetime | str | None
    # Template variables and referenced domain records differ by notification kind.
    # Keep their native JSON rather than narrowing or rewriting business content.
    message_vars: dict[str, JsonValue]
    records: dict[str, dict[str, JsonValue]]
    notifier_user: dict[str, JsonValue] | None = None
    notifier_bot: dict[str, JsonValue] | None = None

    @field_validator("message_vars", "records", "notifier_user", "notifier_bot", mode="before")
    @classmethod
    def serialize_native_json(cls, value):
        # Domain notification records can contain SafeDateTime instances.
        return TypeAdapter(dict).dump_python(value, mode="json") if isinstance(value, dict) else value

    @model_validator(mode="after")
    def require_one_notifier(self):
        if (self.notifier_user is None) == (self.notifier_bot is None):
            raise ValueError("Expected exactly one notification actor")
        return self


class UnreadNotificationsOutput(CommandOutput):
    notifications: list[NotificationOutput]
    returned_count: int = Field(ge=0, le=50)

    @model_validator(mode="after")
    def require_matching_count(self):
        if self.returned_count != len(self.notifications):
            raise ValueError("Notification count does not match the returned page")
        return self


NOTIFICATION_OUTPUTS = {"get_unread_notifications": UnreadNotificationsOutput}
