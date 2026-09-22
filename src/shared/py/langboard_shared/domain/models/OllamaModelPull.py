from enum import Enum
from typing import Any
from sqlalchemy import TEXT
from ...core.db import BaseDbModel, DateTimeField, EnumLikeType, Field
from ...core.types import SafeDateTime


class OllamaModelPullStatus(Enum):
    Pending = "pending"
    Queued = "queued"
    Running = "running"
    Success = "success"
    Failed = "failed"
    Uncertain = "uncertain"


class OllamaModelPull(BaseDbModel, table=True):
    model_name: str = Field(nullable=False, unique=True, max_length=255)
    status: OllamaModelPullStatus = Field(
        default=OllamaModelPullStatus.Pending,
        nullable=False,
        index=True,
        sa_type=EnumLikeType(OllamaModelPullStatus)(length=20),
    )
    attempt: int = Field(default=1, nullable=False)
    percent: float = Field(default=0.0, nullable=False)
    status_text: str | None = Field(default=None, nullable=True, max_length=255)
    failure_reason: str | None = Field(default=None, nullable=True, sa_type=TEXT)
    claimed_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["model_name", "status", "attempt", "percent"]
