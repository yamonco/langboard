"""Runtime-specific revocable permit; acquiring it is not proof of execution."""

from typing import Any
from sqlalchemy import JSON, CheckConstraint
from ...core.db import BaseDbModel, DateTimeField, Field, SnowflakeIDField
from ...core.types import SafeDateTime


class AppExecutionLease(BaseDbModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "state IN ('authorized','stop_requested','stopped')",
            name="ck_app_execution_lease_state",
        ),
    )
    request_id: int = SnowflakeIDField(nullable=False, unique=True)
    acknowledgment_id: int = SnowflakeIDField(nullable=False)
    runtime_token_hash: str = Field(nullable=False)
    state: str = Field(default="authorized", nullable=False)
    expires_at: SafeDateTime = DateTimeField(default=SafeDateTime.now, nullable=False)
    history: list[dict[str, Any]] = Field(default_factory=list, nullable=False, sa_type=JSON)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["request_id", "state"]
