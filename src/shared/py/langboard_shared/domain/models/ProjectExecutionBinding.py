from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Project import Project


class ProjectExecutionBinding(BaseDbModel, table=True):
    """Optional board-owned mapping from columns to external work semantics."""

    project_id: SnowflakeID = SnowflakeIDField(foreign_key=Project, nullable=False, unique=True)
    is_enabled: bool = Field(default=False, nullable=False, api_field=ApiField())
    column_semantics: dict[str, str] = Field(default_factory=dict, sa_type=JSON, nullable=False, api_field=ApiField())
    column_semantic_ids: dict[str, str] = Field(default_factory=dict, sa_type=JSON, nullable=False)
    prerequisite_relationship_type_uid: str | None = Field(default=None, nullable=True, api_field=ApiField())
    prerequisite_relationship_type_id: SnowflakeID | None = SnowflakeIDField(nullable=True)
    webhook_uid: str | None = Field(default=None, nullable=True, api_field=ApiField())
    webhook_id: SnowflakeID | None = SnowflakeIDField(nullable=True)
    events: list[str] = Field(default_factory=list, sa_type=JSON, nullable=False, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["project_id", "is_enabled"]
