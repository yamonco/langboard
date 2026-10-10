"""App ownership is independent of the card's visibility and creator."""

from typing import Any
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Card import Card


class CardAppOwnership(BaseDbModel, table=True):
    card_id: SnowflakeID = SnowflakeIDField(foreign_key=Card, nullable=False, unique=True, index=True)
    app_key: str | None = Field(default=None, nullable=True)
    revision: int = Field(default=1, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "app_key", "revision"]


class CardAppOwnershipAudit(BaseDbModel, table=True):
    # No card FK: deleting a card must not cascade away governance evidence.
    card_id: SnowflakeID = SnowflakeIDField(nullable=False, index=True)
    actor_id: SnowflakeID = SnowflakeIDField(nullable=False)
    previous_app_key: str | None = Field(default=None, nullable=True)
    app_key: str | None = Field(default=None, nullable=True)
    revision: int = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "actor_id", "revision"]
