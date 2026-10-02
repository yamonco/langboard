from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field


class ProjectTemplate(BaseDbModel, table=True):
    """Reusable project structure and automation snapshot."""

    name: str = Field(nullable=False, unique=True, index=True, api_field=ApiField())
    columns: list[str | dict[str, Any]] = Field(
        default_factory=list, nullable=False, sa_type=JSON, api_field=ApiField()
    )
    # Legacy input only. Structured columns own descriptions for all new writes.
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

    def column_definitions(self) -> list[dict[str, Any]]:
        """Normalize old positional guidance without guessing stage from a display name."""
        return [
            {
                "name": column,
                "description": self.column_descriptions[index] if index < len(self.column_descriptions) else "",
                "workflow_stage": None,
            }
            if isinstance(column, str)
            else dict(column)
            for index, column in enumerate(self.columns)
        ]

    def api_response(self, **kwargs) -> dict[str, Any]:
        definitions = self.column_definitions()
        return {
            **super().api_response(**kwargs),
            "columns": [column["name"] for column in definitions],
            "column_descriptions": [column.get("description", "") for column in definitions],
            "column_definitions": definitions,
        }

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["name", "is_builtin", "is_default"]
