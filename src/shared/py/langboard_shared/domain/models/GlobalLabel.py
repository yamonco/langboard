from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field


class GlobalLabel(BaseDbModel, table=True):
    """Reusable label definition; project labels remain independent snapshots."""

    name: str = Field(nullable=False, unique=True, api_field=ApiField())
    color: str = Field(nullable=False, api_field=ApiField())
    description: str = Field(default="", nullable=False, api_field=ApiField())

    translations: dict[str, dict[str, str]] = Field(
        default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField()
    )

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["name", "color"]
