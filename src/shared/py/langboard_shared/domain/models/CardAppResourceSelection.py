"""Explicit execution resource selection, independent of check/commit signals."""

from typing import Any
from sqlalchemy import JSON, UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .AppConnection import AppConnection
from .Card import Card


class CardAppResourceSelection(BaseDbModel, table=True):
    __table_args__ = (UniqueConstraint("card_id", "app_key", name="uq_card_app_resource_selection"),)
    card_id: int = SnowflakeIDField(foreign_key=Card, nullable=False, index=True)
    app_key: str = Field(nullable=False)
    connection_id: int = SnowflakeIDField(foreign_key=AppConnection, nullable=False)
    resource_uids: list[str] = Field(default_factory=list, sa_type=JSON, nullable=False)
    revision: int = Field(default=1, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "app_key", "connection_id", "revision"]


class CardAppResourceSelectionAudit(BaseDbModel, table=True):
    # No foreign keys: deleting a card/connection must preserve configuration evidence.
    card_id: int = SnowflakeIDField(nullable=False, index=True)
    actor_id: int = SnowflakeIDField(nullable=False)
    app_key: str = Field(nullable=False)
    connection_id: int = SnowflakeIDField(nullable=False)
    resource_uids: list[str] = Field(default_factory=list, sa_type=JSON, nullable=False)
    revision: int = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "app_key", "revision"]
