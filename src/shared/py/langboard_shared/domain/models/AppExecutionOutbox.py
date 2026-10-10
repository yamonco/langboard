"""App-scoped event identity, independent of the legacy board ready outbox."""

from typing import Any
from sqlalchemy import JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, DateTimeField, Field, SnowflakeIDField
from ...core.types import SafeDateTime


class AppExecutionOutbox(BaseDbModel, table=True):
    __table_args__ = (
        UniqueConstraint("request_id", "event_type", name="uq_app_execution_outbox_request_event"),
        CheckConstraint(
            "state IN ('pending','delivering','delivered','blocked','failed')",
            name=conv("ck_app_execution_outbox_state"),
        ),
    )
    # Event and accepted history survive card/connection deletion.
    request_id: int = SnowflakeIDField(nullable=False, index=True)
    project_id: int = SnowflakeIDField(nullable=False, index=True)
    app_key: str = Field(nullable=False)
    connection_id: int = SnowflakeIDField(nullable=False)
    event_type: str = Field(nullable=False)
    payload: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, nullable=False)
    state: str = Field(default="pending", nullable=False)
    attempt_count: int = Field(default=0, nullable=False)
    lease_until: SafeDateTime | None = DateTimeField(default=None, nullable=True)
    claim_token: str | None = Field(default=None, nullable=True)
    last_error: str | None = Field(default=None, nullable=True)
    delivery_history: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSON, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["request_id", "app_key", "event_type", "state"]
