"""Host audit facts; no credential, vault locator or free-form payload."""

from typing import Any
from sqlalchemy import CheckConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .SecretReference import SecretReference
from .User import User


class SecretReferenceAudit(BaseDbModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "action IN ('created','resolved','renamed','moved','revoked','rotated')",
            name=conv("ck_secret_reference_audit_action"),
        ),
    )
    reference_id: SnowflakeID = SnowflakeIDField(foreign_key=SecretReference, nullable=False, index=True)
    actor_id: SnowflakeID = SnowflakeIDField(foreign_key=User, nullable=False)
    action: str = Field(nullable=False)
    source_kind: str = Field(nullable=False)
    source_uid: str | None = Field(default=None, nullable=True)
    scope: str = Field(nullable=False)
    scope_id: SnowflakeID = SnowflakeIDField(nullable=False)
    reference_revision: int = Field(nullable=False)
    request_id: str | None = Field(default=None, nullable=True)
    reason_code: str | None = Field(default=None, nullable=True)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["reference_id", "actor_id", "action", "reference_revision"]
