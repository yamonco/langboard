"""Immutable app-reported start evidence; never inferred from permit issuance."""

from typing import Any
from ...core.db import BaseDbModel, Field, SnowflakeIDField


class AppExecutionStart(BaseDbModel, table=True):
    lease_id: int = SnowflakeIDField(nullable=False, unique=True)
    request_id: int = SnowflakeIDField(nullable=False)
    acknowledgment_id: int = SnowflakeIDField(nullable=False)
    generation: int = Field(nullable=False)
    runtime_reference: str = Field(nullable=False)
    execution_reference: str = Field(nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["lease_id"]
