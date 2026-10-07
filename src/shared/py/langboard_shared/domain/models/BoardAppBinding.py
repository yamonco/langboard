from typing import Any
from sqlalchemy import JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Project import Project


class BoardAppBinding(BaseDbModel, table=True):
    """Board-owned App settings, independent of the discovery catalog."""

    __table_args__ = (
        UniqueConstraint("project_id", "app_key", name="uq_board_app_binding_project_app"),
        CheckConstraint(
            "state IN ('disabled','enabled','needs_attention','disconnected')", name=conv("ck_board_app_binding_state")
        ),
    )
    project_id: SnowflakeID = SnowflakeIDField(foreign_key=Project, nullable=False, index=True)
    app_key: str = Field(nullable=False)
    state: str = Field(default="disabled", nullable=False)
    workflow_mapping: dict[str, str] = Field(default_factory=dict, sa_type=JSON, nullable=False)
    granted_capabilities: list[str] = Field(default_factory=list, sa_type=JSON, nullable=False)
    stage_transitions_enabled: bool = Field(default=False, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["project_id", "app_key", "state"]
