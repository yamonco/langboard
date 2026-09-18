from typing import Any
from ...core.db import ApiField, EditorContentModel, Field, ModelColumnType, SnowflakeIDField, SoftDeleteModel
from ...core.types import SnowflakeID
from .Bot import Bot
from .Card import Card
from .User import User


class CardComment(SoftDeleteModel, table=True):
    card_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Card, nullable=False, index=True, api_field=ApiField(name="card_uid")
    )
    user_id: SnowflakeID | None = SnowflakeIDField(foreign_key=User, nullable=True)
    bot_id: SnowflakeID | None = SnowflakeIDField(foreign_key=Bot, nullable=True)
    content: EditorContentModel = Field(
        default=EditorContentModel(), sa_type=ModelColumnType(EditorContentModel), api_field=ApiField()
    )
    # Optional anchor tying a comment to a specific description section heading,
    # enabling the reverse gutter navigation from body blocks to comment threads.
    section_anchor: str | None = Field(default=None, nullable=True, api_field=ApiField())

    @classmethod
    def api_schema(cls, schema: dict | None = None) -> dict[str, Any]:
        return super().api_schema(
            {
                "is_edited": "bool",
                **(schema or {}),
            }
        )

    def api_response(self) -> dict[str, Any]:
        return {
            **super().api_response(),
            "is_edited": self.created_at.timestamp() != self.updated_at.timestamp(),
        }

    def notification_data(self) -> dict[str, Any]:
        return {
            "uid": self.get_uid(),
            "content": self.content.model_dump(),
        }

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["card_id", "user_id", "bot_id"]
