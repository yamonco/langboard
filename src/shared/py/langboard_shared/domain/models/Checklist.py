from typing import Any
from sqlalchemy import Index, false, text
from ...core.db import ApiField, Field, SnowflakeIDField, SoftDeleteModel
from ...core.types import SnowflakeID
from .Card import Card


class Checklist(SoftDeleteModel, table=True):
    __table_args__ = (
        Index(
            "uq_checklist_active_system_card",
            "card_id",
            unique=True,
            postgresql_where=text("is_system AND deleted_at IS NULL"),
            sqlite_where=text("is_system = 1 AND deleted_at IS NULL"),
        ),
    )

    card_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Card, nullable=False, index=True, api_field=ApiField(name="card_uid")
    )
    title: str = Field(nullable=False, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    is_checked: bool = Field(default=False, nullable=False, api_field=ApiField())
    # System checklists back hidden single-object behaviors (for example the completion
    # checkbox on a title-only card) and never render as user checklists.
    is_system: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={"server_default": false()},
        api_field=ApiField(),
    )

    def notification_data(self) -> dict[str, Any]:
        return {
            "uid": self.get_uid(),
            "title": self.title,
        }

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["card_id", "title", "order", "is_checked", "is_system"]
