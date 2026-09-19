"""Trigger→action pipeline planning for board workflows.

Matches workflow templates against board events and produces a
deterministic action plan plus run records. Pure planning — side
effects are executed by the infrastructure layer.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Sequence
from .workflow_template import WorkflowAction, WorkflowCondition, WorkflowTemplate, WorkflowTrigger


class WorkflowRunStatus(str, Enum):
    """Outcome of one workflow run."""

    PLANNED = "planned"
    RAN = "ran"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkflowEvent:
    """A normalized board event offered to the pipeline."""

    event_id: str
    project_uid: str
    trigger: WorkflowTrigger
    occurred_at: datetime
    actor: str = ""
    card_uid: str | None = None
    from_column: str | None = None
    to_column: str | None = None
    label: str | None = None
    card_type: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")


@dataclass(frozen=True)
class WorkflowActionPlan:
    """One action selected for execution."""

    template_uid: str
    action: WorkflowAction
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRunRecord:
    """Durable record of a workflow run for audit and retries."""

    run_uid: str
    event_id: str
    template_uid: str
    status: WorkflowRunStatus
    detail: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_payload(self) -> dict[str, Any]:
        """Serialize for persistence."""

        return {
            "run_uid": self.run_uid,
            "event_id": self.event_id,
            "template_uid": self.template_uid,
            "status": self.status.value,
            "detail": self.detail,
            "recorded_at": self.recorded_at.isoformat(),
        }


def condition_matches(condition: WorkflowCondition, event: WorkflowEvent) -> bool:
    """Return whether every declared condition field agrees with the event."""

    checks = (
        (condition.from_column, event.from_column),
        (condition.to_column, event.to_column),
        (condition.label, event.label),
        (condition.card_type, event.card_type),
    )
    return all(expected is None or expected == actual for expected, actual in checks)


def plan_actions(templates: Sequence[WorkflowTemplate], event: WorkflowEvent) -> tuple[WorkflowActionPlan, ...]:
    """Build the deterministic action plan for one event.

    Templates are processed in catalog order (name, uid); enabled
    templates whose trigger and condition match contribute their
    actions in declaration order.
    """

    plans: list[WorkflowActionPlan] = []
    for template in sorted(templates, key=lambda item: (item.name, item.uid)):
        if not template.is_enabled or template.project_uid != event.project_uid:
            continue
        if template.trigger is not event.trigger:
            continue
        if not condition_matches(template.condition, event):
            continue
        for action in template.actions:
            plans.append(
                WorkflowActionPlan(
                    template_uid=template.uid,
                    action=action,
                    params={"card_uid": event.card_uid, "actor": event.actor},
                )
            )
    return tuple(plans)


def record_run(event: WorkflowEvent, plans: Sequence[WorkflowActionPlan], *, run_uid: str) -> tuple[WorkflowRunRecord, ...]:
    """Create one audit record per planned action."""

    if not plans:
        return (
            WorkflowRunRecord(
                run_uid=run_uid,
                event_id=event.event_id,
                template_uid="",
                status=WorkflowRunStatus.SKIPPED,
                detail="no template matched",
            ),
        )
    return tuple(
        WorkflowRunRecord(
            run_uid=f"{run_uid}:{index}",
            event_id=event.event_id,
            template_uid=plan.template_uid,
            status=WorkflowRunStatus.PLANNED,
            detail=plan.action.value,
        )
        for index, plan in enumerate(plans)
    )
