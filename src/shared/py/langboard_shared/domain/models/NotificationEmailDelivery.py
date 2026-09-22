from enum import Enum
from typing import Any
from sqlalchemy import JSON, TEXT
from ...core.db import BaseDbModel, DateTimeField, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .User import User
from .UserNotification import NotificationType


class NotificationEmailDeliveryStatus(Enum):
    Pending = "pending"
    Preparing = "preparing"
    Sending = "sending"
    Sent = "sent"
    Failed = "failed"
    Uncertain = "uncertain"
    Suppressed = "suppressed"
    ConfirmedSent = "confirmed_sent"
    Closed = "closed"


class NotificationEmailDelivery(BaseDbModel, table=True):
    notification_id: SnowflakeID = SnowflakeIDField(nullable=False, unique=True)
    receiver_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, index=True)
    notification_type: NotificationType = Field(nullable=False, sa_type=EnumLikeType(NotificationType))
    scope_models: list[tuple[str, int]] | None = Field(default=None, nullable=True, sa_type=JSON)
    recipient_email: str = Field(nullable=False, max_length=320)
    preferred_lang: str = Field(nullable=False, max_length=20)
    template_name: str = Field(nullable=False, max_length=64)
    formats: dict[str, str] = Field(default_factory=dict, nullable=False, sa_type=JSON)
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
        return ["notification_id", "receiver_id", "status"]
