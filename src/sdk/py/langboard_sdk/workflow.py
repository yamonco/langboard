"""Built-in Langboard workflow types; apps select types, never create stages."""

from dataclasses import dataclass
from enum import StrEnum


class WorkflowStage(StrEnum):
    BACKLOG = "backlog"
    READY = "ready"
    ACTIVE = "active"
    REVIEW = "review"
    CLOSED = "closed"
    REFERENCE = "reference"


@dataclass(frozen=True)
class WorkflowRequirements:
    required: tuple[WorkflowStage, ...]
    optional: tuple[WorkflowStage, ...] = ()

    def __post_init__(self):
        required = tuple(WorkflowStage(stage) for stage in self.required)
        optional = tuple(WorkflowStage(stage) for stage in self.optional)
        if not required or len(set(required + optional)) != len(required + optional):
            raise ValueError("Workflow requirements need distinct built-in stage types")
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "optional", optional)

    def to_dict(self) -> dict[str, list[str]]:
        """Descriptor for host registration; neither stage creation nor a permission grant."""
        return {"required": [stage.value for stage in self.required], "optional": [stage.value for stage in self.optional]}
