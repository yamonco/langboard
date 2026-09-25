from typing import Any
from sqlalchemy import JSON
from ...core.db import ApiField, BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Card import Card


class CardContentBlock(BaseDbModel, table=True):
    """One typed content block (code/diagram/rich text) attached to a card."""

    card_id: SnowflakeID = SnowflakeIDField(foreign_key=Card, nullable=False, index=True, api_field=ApiField(name="card_uid"))
    block_type: str = Field(nullable=False, index=True, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    revision: int = Field(default=1, nullable=False, sa_column_kwargs={"server_default": "1"}, api_field=ApiField())
    payload: dict[str, Any] = Field(default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["card_id", "block_type", "order", "revision"]
