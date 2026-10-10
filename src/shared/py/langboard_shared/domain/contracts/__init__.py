"""WorkEvent contract: Langboard's standard external event envelope.

Langboard emits WorkEvents for action-required business changes; durable
delivery to external channels (YERMESS, Teams) is owned by YAM Runtime
Control, not Langboard itself.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class WorkEventType(str, Enum):
    """Action-required event types prioritized for external delivery."""

    CARD_ASSIGNED = "card.assigned"
    CARD_MENTIONED = "card.mentioned"
    COMMENT_MENTIONED = "comment.mentioned"
    CHECKLIST_NOTIFY = "checklist.notify"
    APPROVAL_REQUESTED = "card.approval_requested"
    APPROVAL_DECIDED = "card.approval_decided"
    DEADLINE_APPROACHING = "card.deadline_approaching"
    DEADLINE_OVERDUE = "card.deadline_overdue"
    ONBOARDING_FAILED = "project.onboarding_failed"
    CARD_CREATED = "card.created"
    WIKI_MENTIONED = "wiki.mentioned"


class WorkEventScope(str, Enum):
    """The resource a WorkEvent pertains to."""

    PROJECT = "project"
    CARD = "card"
    WIKI = "wiki"


@dataclass(frozen=True)
class WorkEventActor:
    """The principal that caused the event (user, bot, or system)."""

    principal_type: str  # "user" | "bot" | "system"
    principal_id: str
    display_name: str


@dataclass(frozen=True)
class WorkEvent:
    """The standard external event envelope Langboard publishes.

    Contract guarantees:
    - `event_id` is globally unique and stable; consumers use it for idempotent retries.
    - `actor` is always populated (who caused the change).
    - `scope` identifies the affected resource.
    - `payload_hash` enables integrity verification.
    - `correlation_id` links related events (e.g., a mention chain).
    """

    event_id: str
    event_type: WorkEventType
    actor: WorkEventActor
    scope_type: WorkEventScope
    scope_id: str
    project_uid: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    payload_hash: str = ""
    correlation_id: str = ""


@dataclass(frozen=True)
class WorkEventEnvelope:
    """Wire format for the WorkEvent as published to the external bus."""

    spec_version: str = "1.0"
    event: WorkEvent | None = None
    source: str = "langboard"

    def to_dict(self) -> dict[str, Any]:
        if self.event is None:
            return {"spec_version": self.spec_version, "source": self.source}
        e = self.event
        return {
            "spec_version": self.spec_version,
            "source": self.source,
            "event_id": e.event_id,
            "event_type": e.event_type.value,
            "actor": {
                "principal_type": e.actor.principal_type,
                "principal_id": e.actor.principal_id,
                "display_name": e.actor.display_name,
            },
            "scope": {
                "type": e.scope_type.value,
                "id": e.scope_id,
                "project_uid": e.project_uid,
            },
            "occurred_at": e.occurred_at.isoformat(),
            "payload": e.payload,
            "payload_hash": e.payload_hash,
            "correlation_id": e.correlation_id,
        }


class WorkEventFilter:
    """Determines which internal events are worth external delivery.

    Low-value events (reactions, simple moves, view changes) are excluded.
    Action-required events (assign, mention, approval, deadline) are included.
    """

    EXCLUDED_TYPES: frozenset[str] = frozenset({
        "comment.reacted",
        "card.viewed",
        "card.moved",
        "card.order_changed",
        "checklist.item_checked",
        "checklist.item_unchecked",
    })

    @classmethod
    def should_emit(cls, event_type: str) -> bool:
        return event_type not in cls.EXCLUDED_TYPES

    @classmethod
    def action_required_types(cls) -> list[WorkEventType]:
        return [
            WorkEventType.CARD_ASSIGNED,
            WorkEventType.CARD_MENTIONED,
            WorkEventType.COMMENT_MENTIONED,
            WorkEventType.CHECKLIST_NOTIFY,
            WorkEventType.APPROVAL_REQUESTED,
            WorkEventType.APPROVAL_DECIDED,
            WorkEventType.DEADLINE_APPROACHING,
            WorkEventType.DEADLINE_OVERDUE,
            WorkEventType.ONBOARDING_FAILED,
        ]
