from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field


class ProjectTemplate(BaseDbModel, table=True):
    """Reusable project structure and automation snapshot."""

    name: str = Field(nullable=False, unique=True, index=True, api_field=ApiField())
    columns: list[str] = Field(default_factory=list, nullable=False, sa_type=JSON, api_field=ApiField())
    # Aligned with columns by position, preserving distinct descriptions for duplicate names.
    column_descriptions: list[str] = Field(default_factory=list, nullable=False, sa_type=JSON, api_field=ApiField())
    internal_bots: list[dict[str, Any]] = Field(default_factory=list, nullable=False, sa_type=JSON)
    project_bot_scopes: list[dict[str, Any]] = Field(default_factory=list, nullable=False, sa_type=JSON)
    column_bot_scopes: list[dict[str, Any]] = Field(default_factory=list, nullable=False, sa_type=JSON)
    email_notification_policy: dict[str, Any] = Field(
        default_factory=dict,
        nullable=False,
        sa_type=JSON,
        api_field=ApiField(),
    )
    is_builtin: bool = Field(default=False, nullable=False, api_field=ApiField())
    is_default: bool = Field(default=False, nullable=False, index=True, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["name", "is_builtin", "is_default"]
