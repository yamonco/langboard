from typing import Any
from sqlalchemy import TEXT
from ...core.db import BaseDbModel, DateTimeField, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .NotificationEmailDelivery import NotificationEmailDeliveryStatus
from .Project import Project


class ProjectActivityEmailDelivery(BaseDbModel, table=True):
    project_id: SnowflakeID = SnowflakeIDField(foreign_key=Project, nullable=False, index=True)
    activity_table: str = Field(nullable=False, max_length=64, unique_groups=("activity_recipient",))
    activity_id: SnowflakeID = SnowflakeIDField(nullable=False, unique_groups=("activity_recipient",))
    recipient_email: str = Field(nullable=False, max_length=320, unique_groups=("activity_recipient",))
    status: NotificationEmailDeliveryStatus = Field(
        default=NotificationEmailDeliveryStatus.Pending,
        nullable=False,
        index=True,
        sa_type=EnumLikeType(NotificationEmailDeliveryStatus)(length=20),
    )
    claimed_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)
    sent_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)
    failure_reason: str | None = Field(default=None, nullable=True, sa_type=TEXT)
    review_note: str | None = Field(default=None, nullable=True, sa_type=TEXT)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["project_id", "activity_table", "activity_id", "recipient_email", "status"]
