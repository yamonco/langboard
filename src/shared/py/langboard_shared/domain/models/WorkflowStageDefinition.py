import hashlib
import json
from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field


class WorkflowStageDefinition(BaseDbModel, table=True):
    """Global workflow semantics referenced by immutable keys."""

    key: str = Field(nullable=False, unique=True, index=True, api_field=ApiField())
    name: str = Field(nullable=False, api_field=ApiField())
    description: str = Field(default="", nullable=False, api_field=ApiField())
    color: str = Field(default="#64748B", nullable=False, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    is_builtin: bool = Field(default=False, nullable=False, api_field=ApiField())
    is_active: bool = Field(default=True, nullable=False, api_field=ApiField())
    counts_as_completed: bool = Field(default=False, nullable=False, api_field=ApiField())
    active_queue_policy: str = Field(default="conditional", nullable=False, api_field=ApiField())
    overdue_policy: str = Field(default="normal", nullable=False, api_field=ApiField())
    entry_effects: list[str] = Field(default_factory=list, nullable=False, sa_type=JSON, api_field=ApiField())
    translations: dict[str, dict[str, str]] = Field(
        default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField()
    )

    def notification_data(self) -> dict[str, Any]:
        return {}

    def edit_revision(self) -> str:
        payload = json.dumps(super().api_response(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def api_response(self, **kwargs) -> dict[str, Any]:
        return {**super().api_response(**kwargs), "revision": self.edit_revision()}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["key", "name", "is_active"]
