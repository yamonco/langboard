from datetime import datetime
from typing import Any
from sqlalchemy import JSON, BigInteger, CheckConstraint, Index, UniqueConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .AppConnection import AppConnection


class GitHubSignalDelivery(BaseDbModel, table=True):
    """Verified minimal evidence plus a leased, durable resource dispatch cursor."""

    __table_args__ = (
        UniqueConstraint("connection_id", "event_id", name="uq_github_signal_delivery"),
        CheckConstraint("state IN ('pending','processing','completed','blocked','failed')", name=conv("ck_github_signal_state")),
        Index("ix_github_signal_due", "state", "available_at"),
    )
    connection_id: int = SnowflakeIDField(foreign_key=AppConnection, nullable=False)
    connection_revision: str = Field(nullable=False)
    secret_revision: int = Field(nullable=False)
    event_id: str = Field(nullable=False)
    installation_id: str = Field(nullable=False)
    account_id: str = Field(nullable=False)
    repository_id: str = Field(nullable=False)
    evidence: dict[str, str] = Field(sa_type=JSON, nullable=False)
    resource_after: int = Field(default=0, sa_type=BigInteger, nullable=False)
    resource_upper: int = Field(sa_type=BigInteger, nullable=False)
    skipped_resources: int = Field(default=0, nullable=False)
    state: str = Field(default="pending", nullable=False)
    attempts: int = Field(default=0, nullable=False)
    available_at: datetime = Field(nullable=False)
    lease_token: str | None = Field(default=None, nullable=True)
    last_error: str | None = Field(default=None, nullable=True)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["connection_id", "event_id", "state"]
