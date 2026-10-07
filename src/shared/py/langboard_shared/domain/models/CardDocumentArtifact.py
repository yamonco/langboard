"""Internal structural extraction; never part of attachment or socket payloads."""

from typing import Any
from sqlalchemy import TEXT
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .CardAttachment import CardAttachment


class CardDocumentArtifact(BaseDbModel, table=True):
    attachment_id: SnowflakeID = SnowflakeIDField(foreign_key=CardAttachment, nullable=False, unique=True)
    document_json: str = Field(nullable=False, exclude=True, sa_type=TEXT)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["attachment_id"]
