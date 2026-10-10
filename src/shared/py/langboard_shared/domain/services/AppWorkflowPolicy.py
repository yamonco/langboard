"""App workflow requirements over host-authorized current board columns."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from ..models import ProjectColumn, WorkflowStageDefinition


@dataclass(frozen=True)
class WorkflowRequirements:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    def __post_init__(self):
        keys = self.required + self.optional
        if not self.required or any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("Workflow requirements need distinct nonempty stage keys")


GITHUB_WORKFLOW_REQUIREMENTS = WorkflowRequirements(("active", "review", "closed"), ("ready",))
GLITCHTIP_WORKFLOW_REQUIREMENTS = WorkflowRequirements(("active", "review", "closed"))

# Host-owned presets. Unknown providers cannot grant transitions by supplying a
# smaller requirements object. Other providers join after their contract exists.
APP_WORKFLOW_REQUIREMENTS = MappingProxyType(
    {
        "github": GITHUB_WORKFLOW_REQUIREMENTS,
        "glitchtip": GLITCHTIP_WORKFLOW_REQUIREMENTS,
    }
)


@dataclass(frozen=True)
class WorkflowChoice:
    stage: str
    required: bool
    status: Literal["missing", "ambiguous", "resolved", "invalid"]
    column_uid: str | None
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowMappingResult:
    choices: tuple[WorkflowChoice, ...]

    @property
    def transitions_enabled(self) -> bool:
        return all(
            choice.status == "resolved" if choice.required else choice.status in {"missing", "resolved"}
            for choice in self.choices
        )


def resolve_app_workflow(
    requirements: WorkflowRequirements,
    project_id: int,
    columns: Sequence[ProjectColumn],
    stages: Sequence[WorkflowStageDefinition],
    explicit: Mapping[str, str],
    *,
    authorized_column_ids: frozenset[int],
) -> WorkflowMappingResult:
    """Never infer stages from titles or let a saved mapping grant column access.

    The host supplies current rows and authorized IDs after its own ACL check.
    A stale explicit choice is invalid, not silently replaced with another column.
    Mapping only enables optional transitions; it does not disable signal reads.
    """
    keys = requirements.required + requirements.optional
    if set(explicit) - set(keys):
        raise ValueError("Explicit mapping contains an undeclared workflow stage")
    active = {stage.key for stage in stages if stage.is_active}
    eligible = {
        column.get_uid(): column
        for column in columns
        if column.project_id == project_id
        and column.id in authorized_column_ids
        and not column.deleted_at
        and not column.is_archive
    }
    choices = []
    for key in keys:
        candidates = tuple(
            sorted(uid for uid, column in eligible.items() if column.workflow_stage == key and key in active)
        )
        selected = explicit.get(key)
        if key in explicit:
            status = "resolved" if selected in candidates else "invalid"
        elif key not in active:
            status = "invalid" if key in requirements.required else "missing"
        elif not candidates:
            status = "missing"
        elif len(candidates) > 1:
            status = "ambiguous"
        else:
            status = "resolved"
            selected = candidates[0]
        choices.append(
            WorkflowChoice(
                key, key in requirements.required, status, selected if status == "resolved" else None, candidates
            )
        )
    return WorkflowMappingResult(tuple(choices))
