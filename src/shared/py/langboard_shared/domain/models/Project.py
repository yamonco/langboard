from typing import Any
from sqlalchemy import TEXT
from ...core.db import ApiField, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .BaseNotificationScheduleModel import BaseNotificationScheduleModel
from .Organization import Organization
from .User import User


class Project(BaseNotificationScheduleModel, table=True):
    owner_id: SnowflakeID = SnowflakeIDField(
        foreign_key=User, nullable=False, index=True, api_field=ApiField(name="owner_uid")
    )
    organization_id: SnowflakeID | None = SnowflakeIDField(
        foreign_key=Organization, nullable=True, index=True, api_field=ApiField(name="organization_uid")
    )
    title: str = Field(nullable=False, api_field=ApiField())
    description: str | None = Field(default=None, sa_type=TEXT, api_field=ApiField())
    ai_description: str | None = Field(default=None, sa_type=TEXT, api_field=ApiField())
    project_type: str = Field(default="Other", nullable=False, api_field=ApiField())
    archive_visible_days: int = Field(default=3, nullable=False, api_field=ApiField())
    dock_revision: int = Field(
        default=0,
        nullable=False,
        sa_column_kwargs={"server_default": "0"},
        api_field=ApiField(),
    )

    def notification_data(self) -> dict[str, Any]:
        return {
            "uid": self.get_uid(),
            "title": self.title,
        }

    @classmethod
    def get_notification_schedule_rule_fields(cls) -> list[dict[str, Any]]:
        return [
            {"key": "created_at", "operators": [cls.OPERATOR_OLDER_THAN_DAYS]},
            {"key": "updated_at", "operators": [cls.OPERATOR_OLDER_THAN_DAYS]},
        ]

    @classmethod
    def get_notification_schedule_rule_recipients(cls) -> list[str]:
        return [cls.RECIPIENT_PROJECT_OWNER, cls.RECIPIENT_PROJECT_MEMBERS]

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["owner_id", "organization_id", "title", "project_type", "archive_visible_days"]
