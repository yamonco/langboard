"""Hashed inbound credential; never an external provider secret or user API key."""

from typing import Any
from ...core.db import BaseDbModel, DateTimeField, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .AppConnection import AppConnection
from .User import User


class AppConnectionCredential(BaseDbModel, table=True):
    connection_id: SnowflakeID = SnowflakeIDField(foreign_key=AppConnection, nullable=False, index=True)
    issued_by: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False)
    token_hash: str = Field(nullable=False, unique=True)
    identity_hash: str = Field(nullable=False)
    expires_at: SafeDateTime = DateTimeField(default=None, nullable=False)
    revoked_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["connection_id", "expires_at", "revoked_at"]
