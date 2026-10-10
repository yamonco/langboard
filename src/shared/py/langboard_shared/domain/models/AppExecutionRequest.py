"""Durable request acceptance, separate from delivery and runtime acknowledgment."""

from typing import Any
from sqlalchemy import JSON, UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField


class AppExecutionRequest(BaseDbModel, table=True):
    __table_args__ = (UniqueConstraint("card_id", "generation", name="uq_app_execution_request_generation"),)
    # No foreign keys: configuration/card deletion must not remove accepted history.
    project_id: int = SnowflakeIDField(nullable=False, index=True)
    card_id: int = SnowflakeIDField(nullable=False, index=True)
    app_key: str = Field(nullable=False)
    connection_id: int = SnowflakeIDField(nullable=False)
    generation: int = Field(nullable=False)
    authority: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "app_key", "generation"]
