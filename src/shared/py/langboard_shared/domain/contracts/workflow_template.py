"""Workflow template entities for AI-driven board automation.

A template binds one board event trigger to an ordered list of actions
with an optional condition. Pure frozen contracts; persistence and
execution live elsewhere.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowTrigger(str, Enum):
    """Board events that can start a workflow."""

    CARD_CREATED = "card_created"
    CARD_MOVED = "card_moved"
    CARD_COMMENTED = "card_commented"
    CHECKLIST_COMPLETED = "checklist_completed"
    CARD_ARCHIVED = "card_archived"
    PR_OPENED = "pr_opened"
    REVIEW_COMMENTED = "review_commented"


class WorkflowAction(str, Enum):
    """Actions a workflow can perform."""

    ASSIGN_REVIEWER = "assign_reviewer"
    ADD_LABEL = "add_label"
    MOVE_CARD = "move_card"
    CREATE_CARD = "create_card"
    REQUEST_AI_REVIEW = "request_ai_review"
    NOTIFY = "notify"


MAX_ACTIONS_PER_TEMPLATE = 10


@dataclass(frozen=True)
class WorkflowCondition:
    """Optional match narrowing for a trigger."""

    from_column: str | None = None
    to_column: str | None = None
    label: str | None = None
    card_type: str | None = None


@dataclass(frozen=True)
class WorkflowTemplate:
    """One trigger→actions automation bound to a project."""

    uid: str
    name: str
    project_uid: str
    trigger: WorkflowTrigger
    actions: tuple[WorkflowAction, ...]
    condition: WorkflowCondition = field(default_factory=WorkflowCondition)
    is_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.uid or not self.name.strip() or not self.project_uid:
            raise ValueError("uid, name and project_uid are required")
        if not self.actions:
            raise ValueError("a template needs at least one action")
        if len(self.actions) > MAX_ACTIONS_PER_TEMPLATE:
            raise ValueError(f"a template allows at most {MAX_ACTIONS_PER_TEMPLATE} actions")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("duplicate actions are not allowed")
        if self.trigger is WorkflowTrigger.CARD_MOVED and self.condition.to_column is None:
            raise ValueError("card_moved templates must declare condition.to_column")

    def to_payload(self) -> dict[str, Any]:
        """Serialize for persistence."""

        return {
            "uid": self.uid,
            "name": self.name,
            "project_uid": self.project_uid,
            "trigger": self.trigger.value,
            "actions": [action.value for action in self.actions],
            "condition": {
                "from_column": self.condition.from_column,
                "to_column": self.condition.to_column,
                "label": self.condition.label,
                "card_type": self.condition.card_type,
            },
            "is_enabled": self.is_enabled,
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "WorkflowTemplate":
        """Restore from a persisted payload."""

        return WorkflowTemplate(
            uid=payload["uid"],
            name=payload["name"],
            project_uid=payload["project_uid"],
            trigger=WorkflowTrigger(payload["trigger"]),
            actions=tuple(WorkflowAction(action) for action in payload["actions"]),
            condition=WorkflowCondition(**payload.get("condition", {})),
            is_enabled=payload.get("is_enabled", True),
        )


class WorkflowTemplateCatalog:
    """In-memory template set with uniqueness and lookup rules."""

    def __init__(self) -> None:
        self._templates: dict[str, WorkflowTemplate] = {}

    def upsert(self, template: WorkflowTemplate) -> None:
        """Add or replace a template, rejecting name collisions per project."""

        for existing in self._templates.values():
            if existing.uid != template.uid and existing.project_uid == template.project_uid and existing.name == template.name:
                raise ValueError(f"template name '{template.name}' already exists in project")
        self._templates[template.uid] = template

    def remove(self, uid: str) -> bool:
        """Remove a template by uid; return whether it existed."""

        return self._templates.pop(uid, None) is not None

    def get(self, uid: str) -> WorkflowTemplate | None:
        """Return one template by uid."""

        return self._templates.get(uid)

    def all(self) -> tuple[WorkflowTemplate, ...]:
        """Return every template ordered by name then uid."""

        return tuple(sorted(self._templates.values(), key=lambda template: (template.name, template.uid)))

    def for_project(self, project_uid: str) -> tuple[WorkflowTemplate, ...]:
        """Return a project's templates, disabled ones excluded."""

        return tuple(template for template in self.all() if template.project_uid == project_uid and template.is_enabled)

    def for_trigger(self, project_uid: str, trigger: WorkflowTrigger) -> tuple[WorkflowTemplate, ...]:
        """Return enabled templates of a project listening to a trigger."""

        return tuple(template for template in self.for_project(project_uid) if template.trigger is trigger)
