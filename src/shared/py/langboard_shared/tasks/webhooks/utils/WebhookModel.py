from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field


class WebhookModel(BaseModel):
    """Stable at-least-once webhook event envelope."""

    schema_version: Literal["1"] = "1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: str
    data: dict[str, Any]
