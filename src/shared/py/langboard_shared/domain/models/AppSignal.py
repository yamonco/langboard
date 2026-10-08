from typing import Any
from sqlalchemy import UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .AppResourceBinding import AppResourceBinding


class AppSignal(BaseDbModel, table=True):
    """Append-only provider evidence, independent of workflow and reviewer acceptance."""

    __table_args__ = (UniqueConstraint("resource_id", "event_id", name="uq_app_signal_resource_event"),)
    resource_id: int = SnowflakeIDField(foreign_key=AppResourceBinding, nullable=False)
    provider: str = Field(nullable=False)
    event_id: str = Field(nullable=False)
    event_type: str = Field(nullable=False)
    occurred_at: str = Field(nullable=False)
    external_id: str = Field(nullable=False)
    outcome: str = Field(nullable=False)
    commit_sha: str = Field(nullable=False)
    payload_digest: str = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["resource_id", "provider", "event_type", "external_id"]
