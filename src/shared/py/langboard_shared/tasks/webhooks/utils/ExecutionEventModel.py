"""Vendor-neutral work execution events delivered through existing webhooks."""

from pydantic import BaseModel, ConfigDict, Field


WORK_EXECUTION_EVENTS = frozenset({"io.langboard.work.ready.v1"})


class ExecutionEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=1)
    card_uid: str = Field(min_length=1)
    execution_generation: int = Field(ge=1)
    title: str
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    card_url: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)


def cloudevents_fields(event: str, event_id: str, occurred_at: str, data: ExecutionEventData) -> dict:
    """Build the single structured CloudEvents payload for execution events."""

    return {
        "specversion": "1.0",
        "id": event_id,
        "source": f"/projects/{data.project_uid}",
        "subject": f"cards/{data.card_uid}",
        "type": event,
        "time": occurred_at,
        "data": data.model_dump(exclude={"project_uid", "card_uid"}),
    }
