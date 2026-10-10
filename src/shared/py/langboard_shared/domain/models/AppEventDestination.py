"""Administrator-bound app webhook destination; secrets stay in the existing vault."""

from typing import Any
from ...core.db import BaseDbModel, Field, SnowflakeIDField


class AppEventDestination(BaseDbModel, table=True):
    connection_id: int = SnowflakeIDField(nullable=False, unique=True, index=True)
    webhook_id: int = SnowflakeIDField(nullable=False)
    revision: int = Field(default=1, nullable=False)
    target_revision: str = Field(nullable=False)
    trust_revision: str = Field(nullable=False)
    is_enabled: bool = Field(default=True, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["connection_id", "webhook_id", "revision"]
