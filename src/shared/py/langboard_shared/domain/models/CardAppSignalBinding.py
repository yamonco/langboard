from typing import Any
from sqlalchemy import BigInteger, UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .AppResourceBinding import AppResourceBinding
from .Card import Card


class CardAppSignalBinding(BaseDbModel, table=True):
    """Explicit card-to-check-and-commit scope; soft unlink preserves evidence history."""

    __table_args__ = (
        UniqueConstraint("card_id", "resource_id", "external_id", "commit_sha", name="uq_card_app_signal_scope"),
    )
    card_id: int = SnowflakeIDField(foreign_key=Card, nullable=False, index=True)
    resource_id: int = SnowflakeIDField(foreign_key=AppResourceBinding, nullable=False)
    external_id: str = Field(nullable=False)
    commit_sha: str = Field(nullable=False)
    source_change_seq: int = Field(sa_type=BigInteger, nullable=False)
    revision: int = Field(default=0, nullable=False)
    is_enabled: bool = Field(default=True, nullable=False)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self):
        return ["card_id", "resource_id", "external_id", "revision"]
