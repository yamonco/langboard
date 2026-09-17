from typing import Any
from ...core.db import ApiField, Field, SnowflakeIDField, SoftDeleteModel
from ...core.types import SnowflakeID
from .Card import Card


class Checklist(SoftDeleteModel, table=True):
    card_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Card, nullable=False, index=True, api_field=ApiField(name="card_uid")
    )
    title: str = Field(nullable=False, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    is_checked: bool = Field(default=False, nullable=False, api_field=ApiField())
    # System checklists back hidden single-object behaviors (for example the completion
    # checkbox on a title-only card) and never render as user checklists.
    is_system: bool = Field(default=False, nullable=False, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {
            "uid": self.get_uid(),
            "title": self.title,
        }

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["card_id", "title", "order", "is_checked", "is_system"]
