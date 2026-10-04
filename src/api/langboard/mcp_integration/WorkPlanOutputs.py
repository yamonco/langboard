"""Typed preview and durable apply receipts for the atomic native work plan."""

from datetime import datetime
from typing import Literal
from pydantic import Field, field_validator
from ..card_workspace.application.work_plan import WorkPlan
from .CreationOutputs import EditorBodyOutput
from .GraphOutputs import GraphPatchOutput
from .Outputs import CommandOutput


class PlanCountsOutput(CommandOutput):
    cards: int = Field(ge=0, le=7)
    cardifications: int = Field(ge=0, le=7)
    checklists: int = Field(ge=0, le=12)


class WorkPlanPreviewOutput(CommandOutput):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan: WorkPlan
    counts: PlanCountsOutput


class NativePlanCardOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    project_uid: str
    project_column_uid: str
    title: str
    description: EditorBodyOutput
    ai_description: str | None
    deadline_at: datetime | str | None
    order: int = Field(ge=0)
    archived_at: datetime | str | None
    source_type: str | None
    source_uid: str | None
    last_change_seq: int = Field(ge=0)
    last_change_target_type: str
    last_change_target_uid: str | None
    last_change_at: datetime | str | None


class PlanCardificationOutput(CommandOutput):
    card: NativePlanCardOutput
    source_checkitem_uid: str


class NativePlanChecklistOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    card_uid: str
    title: str
    order: int = Field(ge=0)
    is_checked: bool
    is_system: bool


class NativePlanCheckitemOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    checklist_uid: str
    title: str
    status: Literal["started", "paused", "stopped"]
    order: int = Field(ge=0)
    accumulated_seconds: int = Field(ge=0)
    is_checked: bool
    deadline_at: datetime | str | None


class PlanChecklistOutput(CommandOutput):
    target_card_uid: str
    checklist: NativePlanChecklistOutput
    checkitems: list[NativePlanCheckitemOutput] = Field(min_length=1, max_length=25)


class WorkPlanApplyOutput(CommandOutput):
    graph: GraphPatchOutput | None
    cardifications: list[PlanCardificationOutput] = Field(max_length=7)
    checklists: list[PlanChecklistOutput] = Field(max_length=12)
    applied_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    all_succeeded: Literal[True]
    replayed: bool

    @field_validator("all_succeeded", mode="before")
    @classmethod
    def require_true_boolean(cls, value):
        if value is not True:
            raise ValueError("Expected true boolean")
        return value


WORK_PLAN_OUTPUTS = {
    "preview_card_work_plan": WorkPlanPreviewOutput,
    "apply_card_work_plan": WorkPlanApplyOutput,
}
