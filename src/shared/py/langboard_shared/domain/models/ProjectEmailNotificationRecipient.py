from typing import Any
from ...core.db import BaseDbModel, SnowflakeIDField
from ...core.types import SnowflakeID
from .ProjectEmailNotificationPolicy import ProjectEmailNotificationPolicy
from .User import User


class ProjectEmailNotificationRecipient(BaseDbModel, table=True):
    policy_id: SnowflakeID = SnowflakeIDField(
        foreign_key=ProjectEmailNotificationPolicy,
        nullable=False,
        index=True,
        unique_groups=("policy_user",),
    )
    user_id: SnowflakeID = SnowflakeIDField(
        foreign_key=User,
        nullable=False,
        index=True,
        unique_groups=("policy_user",),
    )

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["policy_id", "user_id"]
