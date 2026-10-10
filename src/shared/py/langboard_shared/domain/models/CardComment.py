from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField
from sqlalchemy import JSON
from ...core.db import ApiField, EditorContentModel, Field, ModelColumnType, SnowflakeIDField, SoftDeleteModel
from ...core.types import SnowflakeID
from .Bot import Bot
from .Card import Card
from .User import User


class CardCommentAnchorModel(BaseModel):
    """A content-based selector for a comment anchored to card description text.

    The exact quote and surrounding context follow the Web Annotation text quote
    selector model. Block text and paths are hints only, so document edits do not
    turn a positional offset into the comment's identity.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"
    version: Literal[1] = 1
    exact: str = PydanticField(min_length=1, max_length=4096)
    prefix: str = PydanticField(default="", max_length=256)
    suffix: str = PydanticField(default="", max_length=256)
    start_block: str = PydanticField(default="", max_length=4096)
    end_block: str = PydanticField(default="", max_length=4096)
    start_path: list[Annotated[int, PydanticField(ge=0)]] = PydanticField(default_factory=list, max_length=16)
    end_path: list[Annotated[int, PydanticField(ge=0)]] = PydanticField(default_factory=list, max_length=16)


class CardComment(SoftDeleteModel, table=True):
    card_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Card, nullable=False, index=True, api_field=ApiField(name="card_uid")
    )
    user_id: SnowflakeID | None = SnowflakeIDField(foreign_key=User, nullable=True)
    bot_id: SnowflakeID | None = SnowflakeIDField(foreign_key=Bot, nullable=True)
    content: EditorContentModel = Field(
        default=EditorContentModel(), sa_type=ModelColumnType(EditorContentModel), api_field=ApiField()
    )
    anchor: dict[str, Any] | None = Field(default=None, nullable=True, sa_type=JSON, api_field=ApiField())

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
