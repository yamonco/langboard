from typing import Any
from sqlalchemy import JSON, UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .AppConnection import AppConnection


class GitHubLifecycleReceipt(BaseDbModel, table=True):
    """Verified delivery provenance; no credentials or arbitrary webhook payload."""

    __table_args__ = (UniqueConstraint("connection_id", "delivery_id", name="uq_github_lifecycle_delivery"),)
    connection_id: SnowflakeID = SnowflakeIDField(foreign_key=AppConnection, nullable=False, index=True)
    connection_revision: str = Field(nullable=False)
    delivery_id: str = Field(nullable=False)
    payload_digest: str = Field(nullable=False)
    event: str = Field(nullable=False)
    action: str = Field(nullable=False)
    app_id: str = Field(nullable=False)
    installation_id: str = Field(nullable=False)
    account_id: str = Field(nullable=False)
    added_repository_ids: list[int] = Field(default_factory=list, sa_type=JSON, nullable=False)
    removed_repository_ids: list[int] = Field(default_factory=list, sa_type=JSON, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["connection_id", "delivery_id", "event", "action"]
