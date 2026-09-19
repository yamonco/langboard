from typing import Any
from sqlalchemy import UniqueConstraint
from ...core.db import ApiField, BaseDbModel, DateTimeField, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .Card import Card
from .User import User


class UserCardReadState(BaseDbModel, table=True):
    """Sparse per-user read cursor over the global card change sequence."""

    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_user_card_read_state_user_card"),)

    user_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, index=True)
    card_id: SnowflakeID = SnowflakeIDField(foreign_key=Card, nullable=False, index=True)
    seen_change_seq: int = Field(default=0, nullable=False, api_field=ApiField())
    seen_at: SafeDateTime = DateTimeField(default=SafeDateTime.now, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["user_id", "card_id", "seen_change_seq", "seen_at"]
