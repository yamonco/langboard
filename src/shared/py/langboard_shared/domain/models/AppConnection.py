from typing import Any
from sqlalchemy import CheckConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .User import User


class AppConnection(BaseDbModel, table=True):
    """Reusable external account; credentials belong to a host secret store."""

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','connected','revoked','disconnected')", name=conv("ck_app_connection_state")
        ),
    )
    app_key: str = Field(nullable=False, index=True)
    owner_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False, index=True)
    instance_url: str = Field(default="", nullable=False)
    external_account_id: str = Field(default="", nullable=False)
    credential_reference: str | None = Field(default=None, nullable=True)
    state: str = Field(default="pending", nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["app_key", "owner_id", "state"]
