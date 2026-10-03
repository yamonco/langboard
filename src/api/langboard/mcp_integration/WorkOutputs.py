"""Typed public work projections, preserving omitted fields and pagination."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_serializer, model_validator
from .Outputs import CommandOutput


class ProjectionOutput(CommandOutput):
    @model_validator(mode="before")
    @classmethod
    def from_domain_dto(cls, value):
        return value.model_dump() if isinstance(value, BaseModel) else value

    @model_serializer(mode="wrap")
    def preserve_omitted_fields(self, handler):
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class PublicCardOutput(ProjectionOutput):
    uid: str
    title: str | None = None
    title_total_chars: int | None = None
    title_truncated: bool | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    can_delete: bool | None = None


class CheckitemOutput(PublicCardOutput):
    order: int | None = None
    is_checked: bool | None = None
    deadline_at: datetime | str | None = None
    status: Literal["started", "paused", "stopped"] | None = None
    cardified_card: PublicCardOutput | None = None


class ChecklistOutput(PublicCardOutput):
    order: int | None = None
    is_checked: bool | None = None
    checkitems: list[CheckitemOutput]
    checkitems_total_count: int = Field(ge=0)
    checkitems_next_cursor: str | None


class ChecklistCreationOutput(CommandOutput):
    checklist: ChecklistOutput


class CheckitemCreationOutput(CommandOutput):
    checkitem: CheckitemOutput


class ChecklistPageOutput(ProjectionOutput):
    items: list[ChecklistOutput]
    total_count: int = Field(ge=0)
    next_cursor: str | None
    limit: int = Field(ge=1)


class ChecklistUpdateOutput(CommandOutput):
    checklists: ChecklistPageOutput


class WorkTransitionOutput(CommandOutput):
    checkitem_uid: str
    status: Literal["started", "paused", "stopped"]
    is_checked: bool
    user_uid: str


class CommentOutput(ProjectionOutput):
    uid: str
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    content: str
    content_format: Literal["text", "json"]
    content_total_chars: int = Field(ge=0)
    content_truncated: bool
    # These commands return comment.api_response(), without author hydration.
    # Query projections with hydrated authors require their own typed contract.


class CommentMutationOutput(CommandOutput):
    comment: CommentOutput


class PublicMetadataOutput(CommandOutput):
    key: str
    value: str
    total_chars: int = Field(ge=0)
    truncated: bool


WORK_OUTPUTS = {
    "create_card_checklist": ChecklistCreationOutput,
    "create_card_checkitem": CheckitemCreationOutput,
    "update_card_checklist": ChecklistUpdateOutput,
    "update_card_checkitem": ChecklistUpdateOutput,
    "change_card_checkitem_work": WorkTransitionOutput,
    "add_card_comment": CommentMutationOutput,
    "update_card_comment": CommentMutationOutput,
    "save_public_card_metadata": PublicMetadataOutput,
}
