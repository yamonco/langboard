from typing import Any
from ...core.db import ApiField, BaseDbModel, DateTimeField, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .User import User


class Organization(BaseDbModel, table=True):
    """Top-level tenant boundary owning projects, groups, and members."""

    name: str = Field(nullable=False, index=True, api_field=ApiField())
    slug: str = Field(unique=True, nullable=False, index=True, api_field=ApiField())
    owner_user_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, api_field=ApiField(name="owner_user_uid"))
    is_active: bool = Field(default=True, nullable=False, sa_column_kwargs={"server_default": "true"}, api_field=ApiField())
    suspended_at: SafeDateTime | None = DateTimeField(default=None, nullable=True, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["name", "slug", "owner_user_id", "is_active"]
