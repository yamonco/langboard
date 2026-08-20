from enum import Enum
from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, CSVType, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Project import Project
from .User import User


class ProjectEmailNotificationCategory(Enum):
    Board = "board"
    Cards = "cards"
    Comments = "comments"
    Attachments = "attachments"
    Checklists = "checklists"
    Wiki = "wiki"


class ProjectEmailNotificationPolicy(BaseDbModel, table=True):
    project_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Project,
        nullable=False,
        unique=True,
        index=True,
    )
    is_enabled: bool = Field(default=False, nullable=False, api_field=ApiField())
    notify_all_members: bool = Field(default=False, nullable=False, api_field=ApiField())
    categories: list[ProjectEmailNotificationCategory] = Field(
        default_factory=list,
        nullable=False,
        sa_type=CSVType(ProjectEmailNotificationCategory),
        api_field=ApiField(),
    )
    card_move_target_columns: list[str] = Field(
        default_factory=list,
        nullable=False,
        sa_type=JSON,
        api_field=ApiField(),
    )

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["project_id", "is_enabled", "notify_all_members", "categories", "card_move_target_columns"]


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
