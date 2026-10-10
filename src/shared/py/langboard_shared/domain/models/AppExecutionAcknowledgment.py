"""App receipt confirms event reception, never execution start or approval."""
from typing import Any
from ...core.db import BaseDbModel, Field, SnowflakeIDField


class AppExecutionAcknowledgment(BaseDbModel, table=True):
    request_id: int = SnowflakeIDField(nullable=False, unique=True)
    event_id: int = SnowflakeIDField(nullable=False)
    connection_id: int = SnowflakeIDField(nullable=False)
    app_key: str = Field(nullable=False)
    runtime_reference: str = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["request_id", "app_key"]
