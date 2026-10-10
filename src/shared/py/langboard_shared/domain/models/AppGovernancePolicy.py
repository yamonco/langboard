"""One indexed policy row per instance or organization scope."""

from typing import Any
from sqlalchemy import CheckConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Organization import Organization


class AppGovernancePolicy(BaseDbModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "(mode IS NOT NULL AND mode IN ('disabled','approved_only','personal_allowed')) OR (mode IS NULL AND organization_id IS NOT NULL)",
            name=conv("ck_app_governance_policy_mode"),
        ),
        CheckConstraint(
            "(scope_key = 'global' AND organization_id IS NULL) OR "
            "(organization_id IS NOT NULL AND scope_key = 'organization:' || CAST(organization_id AS VARCHAR))",
            name=conv("ck_app_governance_policy_scope"),
        ),
    )
    scope_key: str = Field(nullable=False, unique=True, index=True)
    organization_id: SnowflakeID | None = SnowflakeIDField(foreign_key=Organization, nullable=True, unique=True)
    mode: str | None = Field(default="approved_only", nullable=True)
    generation: int = Field(default=1, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["scope_key", "mode", "generation"]
