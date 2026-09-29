from typing import Any
from sqlalchemy import JSON, BigInteger, CheckConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .Card import Card


class CardVerificationRecord(BaseDbModel, table=True):
    """Append-only, revision-bound reviewer evidence; never generic metadata."""

    __table_args__ = (
        CheckConstraint("decision IN ('verified', 'partial', 'unverified')", name="verification_decision"),
        CheckConstraint("(recorded_by_user_id IS NULL) <> (recorded_by_bot_id IS NULL)", name="verification_actor"),
    )
    card_id: SnowflakeID = SnowflakeIDField(foreign_key=Card, nullable=False, index=True)
    source_change_seq: int = Field(nullable=False, sa_type=BigInteger)
    decision: str = Field(nullable=False)
    recorded_by_user_id: SnowflakeID | None = SnowflakeIDField(nullable=True)
    recorded_by_bot_id: SnowflakeID | None = SnowflakeIDField(nullable=True)
    evidence: list[dict[str, Any]] = Field(default_factory=list, nullable=False, sa_type=JSON)
    required_checkitem_uids: list[str] = Field(default_factory=list, nullable=False, sa_type=JSON)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "source_change_seq", "decision"]
