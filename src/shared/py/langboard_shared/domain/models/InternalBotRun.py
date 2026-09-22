from enum import Enum
from typing import Any
from sqlalchemy import JSON, TEXT
from ...core.db import BaseDbModel, DateTimeField, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .ChatHistory import ChatHistory
from .ChatSession import ChatSession
from .InternalBot import InternalBot
from .Project import Project
from .User import User


class InternalBotRunKind(Enum):
    BoardChat = "board_chat"
    EditorChat = "editor_chat"
    EditorCopilot = "editor_copilot"


class InternalBotRunStatus(Enum):
    Accepted = "accepted"
    Streaming = "streaming"
    AwaitingApproval = "awaiting_approval"
    Resuming = "resuming"
    Completed = "completed"
    Failed = "failed"
    Cancelled = "cancelled"
    Uncertain = "uncertain"


class InternalBotRun(BaseDbModel, table=True):
    request_key: str = Field(nullable=False, unique=True, max_length=64)
    request_digest: str = Field(nullable=False, max_length=64)
    client_task_id: str = Field(nullable=False, max_length=128)
    user_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, index=True)
    project_id: SnowflakeID = SnowflakeIDField(foreign_key=Project, nullable=False, index=True)
    internal_bot_id: SnowflakeID = SnowflakeIDField(foreign_key=InternalBot, nullable=False)
    chat_session_id: SnowflakeID | None = SnowflakeIDField(foreign_key=ChatSession, nullable=True)
    chat_history_id: SnowflakeID | None = SnowflakeIDField(foreign_key=ChatHistory, nullable=True)
    ai_chat_history_id: SnowflakeID | None = SnowflakeIDField(foreign_key=ChatHistory, nullable=True)
    kind: InternalBotRunKind = Field(nullable=False, sa_type=EnumLikeType(InternalBotRunKind)(length=20))
    status: InternalBotRunStatus = Field(
        default=InternalBotRunStatus.Accepted,
        nullable=False,
        index=True,
        sa_type=EnumLikeType(InternalBotRunStatus)(length=20),
    )
    scope_table: str = Field(default="project", nullable=False, max_length=32)
    scope_uid: str | None = Field(default=None, nullable=True, max_length=32)
    graph_session_id: str | None = Field(default=None, nullable=True, max_length=512)
    graph_thread_id: str | None = Field(default=None, nullable=True, max_length=1024)
    request_payload: dict[str, Any] = Field(default_factory=dict, nullable=False, sa_type=JSON)
    output_text: str = Field(default="", nullable=False, sa_type=TEXT)
    attempt: int = Field(default=0, nullable=False)
    lease_expires_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)
    finished_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)
    error_message: str | None = Field(default=None, nullable=True, sa_type=TEXT)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["kind", "status", "client_task_id", "attempt"]
