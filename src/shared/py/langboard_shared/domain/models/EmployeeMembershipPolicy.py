"""Operator-selected SCIM membership, shared across API and worker processes."""

from typing import Any
from sqlalchemy import JSON
from ...core.db import BaseDbModel, Field


class EmployeeMembershipPolicy(BaseDbModel, table=True):
    key: str = Field(default="global", nullable=False, unique=True)
    issuer: str = Field(nullable=False)
    group_uids: list[str] = Field(default_factory=list, nullable=False, sa_type=JSON)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["key"]
