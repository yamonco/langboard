"""Private audit evidence; never included in generic card/socket projections."""

from typing import Any
from sqlalchemy import CheckConstraint, Index
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Bot import Bot
from .Card import Card
from .User import User


class CardVisibilityChange(BaseDbModel, table=True):
    __table_args__ = (
        CheckConstraint("previous_visibility IN ('INTERNAL', 'SHARED')", name="visibility_change_previous"),
        CheckConstraint("next_visibility IN ('INTERNAL', 'SHARED')", name="visibility_change_next"),
        CheckConstraint("previous_visibility <> next_visibility", name="visibility_change_distinct"),
        CheckConstraint("(changed_by_user_id IS NULL) <> (changed_by_bot_id IS NULL)", name="visibility_change_actor"),
        CheckConstraint("channel IN ('human_ui','mcp','api','bot')", name="visibility_change_channel"),
        CheckConstraint("next_visibility <> 'SHARED' OR (channel = 'human_ui' AND changed_by_bot_id IS NULL)", name="visibility_change_human_share"),
        Index("ix_card_visibility_change_card_created", "card_id", "created_at", "id"),
    )
    card_id: SnowflakeID = SnowflakeIDField(foreign_key=Card, nullable=False)
    changed_by_user_id: SnowflakeID | None = SnowflakeIDField(foreign_key=User, nullable=True)
    changed_by_bot_id: SnowflakeID | None = SnowflakeIDField(foreign_key=Bot, nullable=True)
    channel: str = Field(nullable=False)
    previous_visibility: str = Field(nullable=False)
    next_visibility: str = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "changed_by_user_id", "changed_by_bot_id", "previous_visibility", "next_visibility"]
