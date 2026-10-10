from typing import Any
from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .AppConnection import AppConnection
from .BoardAppBinding import BoardAppBinding


class AppResourceBinding(BaseDbModel, table=True):
    """Independent resource selection, access and health for one board App."""

    __table_args__ = (
        Index("ix_app_resource_signal_lookup", "connection_id", "resource_type", "external_resource_id", "id"),
        UniqueConstraint(
            "board_binding_id",
            "connection_id",
            "resource_type",
            "external_resource_id",
            name="uq_app_resource_binding_identity",
        ),
        CheckConstraint(
            "access_state IN ('unknown','granted','denied','revoked')", name=conv("ck_app_resource_access_state")
        ),
        CheckConstraint(
            "health IN ('unknown','healthy','degraded','unavailable')", name=conv("ck_app_resource_health")
        ),
    )
    board_binding_id: SnowflakeID = SnowflakeIDField(foreign_key=BoardAppBinding, nullable=False, index=True)
    connection_id: SnowflakeID = SnowflakeIDField(foreign_key=AppConnection, nullable=False, index=True)
    resource_type: str = Field(nullable=False)
    external_resource_id: str = Field(nullable=False)
    resource_path: list[dict[str, str]] = Field(default_factory=list, sa_type=JSON, nullable=False)
    is_selected: bool = Field(default=True, nullable=False)
    access_state: str = Field(default="unknown", nullable=False)
    access_revision: int = Field(default=0, nullable=False)
    health: str = Field(default="unknown", nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["board_binding_id", "connection_id", "resource_type", "access_state", "health"]
