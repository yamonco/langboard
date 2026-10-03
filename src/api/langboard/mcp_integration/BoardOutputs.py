"""Typed board projections retain workflow guidance and partial card edits."""

from datetime import datetime
from typing import Literal
from pydantic import Field
from .Outputs import CommandOutput
from .WorkOutputs import ProjectionOutput


class ColumnTranslationOutput(ProjectionOutput):
    name: str | None = None
    description: str | None = None


class ColumnOutput(ProjectionOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    project_uid: str
    name: str
    description: str
    order: int = Field(ge=0)
    dock_order: int | None = Field(ge=0)
    is_archive: bool
    translations: dict[str, ColumnTranslationOutput]
    workflow_stage: str | None
    count: int = Field(ge=0)
    open_count: int | None = Field(default=None, ge=0)
    incomplete_count: int | None = Field(default=None, ge=0)
    workflow_counts_as_completed: bool | None = None
    workflow_stage_description: str | None = None
    column_description: str | None = None
    workflow_guidance: str | None = None
    workflow_stage_status: Literal["active", "inactive", "missing", "unclassified"] | None = None


class ColumnOrderOutput(CommandOutput):
    column_uid: str
    columns: list[ColumnOutput]


class TemplateProjectOutput(CommandOutput):
    uid: str
    title: str
    project_type: str
    url: str
    template: str


class BoardCreationOutput(CommandOutput):
    project: TemplateProjectOutput
    columns: list[ColumnOutput]


class CardDetailsOutput(ProjectionOutput):
    title: str | None = None
    deadline_at: datetime | str | None = None


BOARD_OUTPUTS = {
    "create_project_board": BoardCreationOutput,
    "create_column": ColumnOutput,
    "change_column_order": ColumnOrderOutput,
    "change_card_details": CardDetailsOutput,
}
