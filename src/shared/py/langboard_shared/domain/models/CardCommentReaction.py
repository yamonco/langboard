from typing import Any
from ...core.db import SnowflakeIDField
from ...core.types import SnowflakeID
from .bases import BaseReactionModel
from .CardComment import CardComment


class CardCommentReaction(BaseReactionModel, table=True):
    comment_id: SnowflakeID = SnowflakeIDField(foreign_key=CardComment, nullable=False, index=True)

    @staticmethod
    def get_target_column_name() -> str:
        return "comment_id"

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return []
