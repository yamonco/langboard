from typing import Any
from sqlalchemy import TEXT
from ...core.db import ApiField, DateTimeField, EditorContentModel, Field, ModelColumnType, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .BaseNotificationScheduleModel import BaseNotificationScheduleModel
from .Project import Project
from .ProjectColumn import ProjectColumn


class Card(BaseNotificationScheduleModel, table=True):
    created_by_user_id: SnowflakeID | None = SnowflakeIDField(nullable=True, index=True)
    created_by_bot_id: SnowflakeID | None = SnowflakeIDField(nullable=True, index=True)
    project_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Project, nullable=False, index=True, api_field=ApiField(name="project_uid")
    )
    project_column_id: SnowflakeID = SnowflakeIDField(
        foreign_key=ProjectColumn, nullable=False, index=True, api_field=ApiField(name="project_column_uid")
    )
    title: str = Field(nullable=False, api_field=ApiField())
    description: EditorContentModel = Field(
        default=EditorContentModel(), sa_type=ModelColumnType(EditorContentModel), api_field=ApiField()
    )
    ai_description: str | None = Field(default=None, sa_type=TEXT, api_field=ApiField())
    deadline_at: SafeDateTime | None = DateTimeField(default=None, nullable=True, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    archived_at: SafeDateTime | None = DateTimeField(default=None, nullable=True, api_field=ApiField())

    def board_api_response(
        self,
        count_comment: int,
        member_uids: list[str],
        relationships: list[dict[str, Any]],
        labels: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            **self.api_response(),
            "count_comment": count_comment,
            "member_uids": member_uids,
            "relationships": relationships,
            "labels": labels,
        }

    def notification_data(self) -> dict[str, Any]:
        return {
            "uid": self.get_uid(),
            "title": self.title,
        }

    @classmethod
    def get_notification_schedule_rule_fields(cls) -> list[dict[str, Any]]:
        return [
            {"key": "deadline_at", "operators": [cls.OPERATOR_WITHIN_NEXT_DAYS, cls.OPERATOR_OVERDUE]},
            {"key": "created_at", "operators": [cls.OPERATOR_OLDER_THAN_DAYS]},
            {"key": "archived_at", "operators": [cls.OPERATOR_IS_EMPTY, cls.OPERATOR_IS_NOT_EMPTY]},
        ]

    @classmethod
    def get_notification_schedule_rule_recipients(cls) -> list[str]:
        return [cls.RECIPIENT_CARD_ASSIGNEES, cls.RECIPIENT_PROJECT_OWNER, cls.RECIPIENT_PROJECT_MEMBERS]

    def get_notification_schedule_rule_message_vars(
        self,
        field: str | None,
        operator: str | None,
        now: SafeDateTime,
    ) -> dict[str, Any] | None:
        if field != "deadline_at" or operator not in [self.OPERATOR_WITHIN_NEXT_DAYS, self.OPERATOR_OVERDUE]:
            return super().get_notification_schedule_rule_message_vars(field, operator, now)
        if not self.deadline_at:
            return None

        return {
            "deadline_at": self.deadline_at.isoformat(),
        }

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["project_id", "project_column_id", "title", "deadline_at", "order", "archived_at"]
