from enum import Enum
from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, DateTimeField, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .User import User


class NotificationType(Enum):
    ProjectInvited = "project_invited"
    MentionedInCard = "mentioned_in_card"
    MentionedInComment = "mentioned_in_comment"
    MentionedInWiki = "mentioned_in_wiki"
    AssignedToCard = "assigned_to_card"
    ReactedToComment = "reacted_to_comment"
    NotifiedFromChecklist = "notified_from_checklist"
    ScheduledRule = "scheduled_rule"


class UserNotification(BaseDbModel, table=True):
    notifier_type: str = Field(nullable=False)
    notifier_id: SnowflakeID = SnowflakeIDField(nullable=False, index=True)
    receiver_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, index=True)
    notification_type: NotificationType = Field(
        nullable=False, sa_type=EnumLikeType(NotificationType), api_field=ApiField(name="type")
    )
    message_vars: dict[str, Any] = Field(default={}, sa_type=JSON, api_field=ApiField())
    record_list: list[tuple[str, SnowflakeID]] = Field(default=[], sa_type=JSON)
    read_at: SafeDateTime | None = DateTimeField(default=None, nullable=True, api_field=ApiField())
    web_visible: bool = Field(default=True)
    work_event_dispatched_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["notifier_id", "receiver_id", "notification_type", "read_at"]
