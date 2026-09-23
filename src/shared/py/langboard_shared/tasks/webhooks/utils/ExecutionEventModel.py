"""Vendor-neutral work execution events delivered through existing webhooks."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


WORK_EXECUTION_EVENTS = frozenset(
    {
        "io.langboard.work.ready.v1",
        "io.langboard.work.blocked.v1",
        "io.langboard.work.cancelled.v1",
        "io.langboard.work.review-requested.v1",
    }
)


class ExecutionEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=1)
    card_uid: str = Field(min_length=1)
    execution_generation: int = Field(ge=1)
    semantic_state: Literal["ready", "active", "review", "terminal", "ignored", "blocked"]
    title: str
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    direct_blocker_uids: list[str] = Field(default_factory=list)
    card_url: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)


def cloudevents_fields(event: str, event_id: str, occurred_at: str, data: ExecutionEventData) -> dict:
    """Map work events to CloudEvents 1.0 without changing the legacy envelope."""

    return {
        "specversion": "1.0",
        "id": event_id,
        "source": f"/projects/{data.project_uid}",
        "subject": f"cards/{data.card_uid}",
        "type": event,
        "time": occurred_at,
    }
