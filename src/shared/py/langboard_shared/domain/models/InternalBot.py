from enum import Enum
from sqlalchemy import Text
from ...core.db import ApiField, EnumLikeType, Field, ModelColumnType
from ...core.storage import FileModel
from .BaseBotModel import BaseBotModel


class InternalBotType(Enum):
    ProjectChat = "project_chat"
    EditorChat = "editor_chat"
    EditorCopilot = "editor_copilot"
    DocumentVision = "document_vision"


class InternalBot(BaseBotModel, table=True):
    bot_type: InternalBotType = Field(nullable=False, sa_type=EnumLikeType(InternalBotType), api_field=ApiField())
    display_name: str = Field(nullable=False, api_field=ApiField())
    api_url: str = Field(default="", nullable=False, api_field=ApiField(by_conditions={"is_setting": ("both", True)}))
    api_key: str = Field(default="", nullable=False, api_field=ApiField(by_conditions={"is_setting": ("both", True)}))
    value: str = Field(
        default="", nullable=False, sa_type=Text, api_field=ApiField(by_conditions={"is_setting": ("both", True)})
    )
    is_default: bool = Field(
        default=False, nullable=False, api_field=ApiField(by_conditions={"is_setting": ("both", True)})
    )
    avatar: FileModel | None = Field(
        default=None, sa_type=ModelColumnType(FileModel), api_field=ApiField(field_base_model="path")
    )

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["bot_type", "display_name", "platform", "platform_running_type", "is_default"]
