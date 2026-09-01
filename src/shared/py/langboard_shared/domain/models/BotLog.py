from enum import Enum
from typing import Any
from pydantic import BaseModel
from ...core.db import ApiField, BaseDbModel, EnumLikeType, Field, ModelColumnListType, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .Bot import Bot


BOT_LOG_MESSAGE_MAX_LENGTH = 4000
BOT_LOG_MESSAGE_STACK_MAX_ITEMS = 200


class BotLogType(Enum):
    Info = "info"
    Success = "success"
    Error = "error"


class BotLogMessage(BaseModel):
    message: str
    log_type: BotLogType
    log_date: SafeDateTime = Field(default_factory=SafeDateTime.now, nullable=False)

    @staticmethod
    def api_schema() -> dict[str, Any]:
        return {"message": "string", "log_type": "string", "log_date": "string"}


class BotLog(BaseDbModel, table=True):
    bot_id: SnowflakeID = SnowflakeIDField(foreign_key=Bot, index=True, api_field=ApiField(name="bot_uid"))
    log_type: BotLogType = Field(
        default=BotLogType.Info, nullable=False, sa_type=EnumLikeType(BotLogType), api_field=ApiField()
    )
    message_stack: list[BotLogMessage] = Field(
        default=[], nullable=False, sa_type=ModelColumnListType(BotLogMessage), api_field=ApiField()
    )

    def append_message(self, message: str, log_type: BotLogType) -> BotLogMessage:
        retained_messages = self.message_stack[-(BOT_LOG_MESSAGE_STACK_MAX_ITEMS - 1) :]
        for retained_message in retained_messages:
            retained_message.message = self._trim_message(retained_message.message)
        log_stack = BotLogMessage(message=self._trim_message(message), log_type=log_type)
        self.message_stack = [*retained_messages, log_stack]
        return log_stack

    @staticmethod
    def _trim_message(message: str) -> str:
        if len(message) <= BOT_LOG_MESSAGE_MAX_LENGTH:
            return message
        return f"{message[: BOT_LOG_MESSAGE_MAX_LENGTH - 3]}..."

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["bot_id", "log_type"]
