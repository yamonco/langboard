from typing import Any
from ...core.db import ApiField, BaseDbModel, Field


class GlobalCardRelationshipType(BaseDbModel, table=True):
    parent_name: str = Field(nullable=False, api_field=ApiField())
    child_name: str = Field(nullable=False, api_field=ApiField())
    description: str = Field(default="", nullable=False, api_field=ApiField())
    machine_semantic: str | None = Field(default=None, nullable=True, api_field=ApiField())
    is_system_default: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}, api_field=ApiField()
    )
    is_active: bool = Field(
        default=True, nullable=False, sa_column_kwargs={"server_default": "true"}, api_field=ApiField()
    )
    affects_readiness: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}, api_field=ApiField()
    )

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["parent_name", "child_name"]
