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


class LabelOutput(ProjectionOutput):
    uid: str
    name: str
    color: str
    description: str | None = None
    order: int | None = None
    global_label_uid: str | None = None
    emoji: str | None = None
    name_total_chars: int | None = None
    name_truncated: bool | None = None
    color_total_chars: int | None = None
    color_truncated: bool | None = None
    description_total_chars: int | None = None
    description_truncated: bool | None = None


class LabelCreationOutput(CommandOutput):
    label: LabelOutput
    created: bool


class GlobalLabelUseOutput(LabelCreationOutput):
    global_label_uid: str


class CardLabelChangeOutput(CommandOutput):
    labels: list[LabelOutput]
    changed: bool


class CatalogLabelOutput(LabelOutput):
    source: Literal["local", "global"]


class LabelCatalogOutput(CommandOutput):
    items: list[CatalogLabelOutput]
    total_count: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)


class MembershipChangeOutput(CommandOutput):
    requested_count: int = Field(ge=0)
    changed_count: int = Field(ge=0)
    status: Literal["updated", "unchanged"]


class PeopleAndLabelsOutput(ProjectionOutput):
    member_uids: list[str] | None = None
    labels: list[LabelOutput] | None = None


class RelationshipOutput(ProjectionOutput):
    uid: str | None = None
    relationship_type_uid: str | None = None
    parent_name: str | None = None
    child_name: str | None = None
    machine_semantic: str | None = None
    affects_readiness: bool | None = None
    is_system_default: bool | None = None
    parent_card_uid: str | None = None
    child_card_uid: str | None = None
    card_uid_parent: str | None = None
    card_uid_child: str | None = None
    parent_name_total_chars: int | None = None
    parent_name_truncated: bool | None = None
    child_name_total_chars: int | None = None
    child_name_truncated: bool | None = None
    machine_semantic_total_chars: int | None = None
    machine_semantic_truncated: bool | None = None


class RelationshipsOutput(CommandOutput):
    relationships: list[RelationshipOutput]


class ChecklistReconcileOutput(ChecklistCreationOutput):
    changed: bool
    receipt: str = Field(pattern=r"^[0-9a-f]{64}$")


WORK_OUTPUTS = {
    "create_card_checklist": ChecklistCreationOutput,
    "create_card_checkitem": CheckitemCreationOutput,
    "update_card_checklist": ChecklistUpdateOutput,
    "update_card_checkitem": ChecklistUpdateOutput,
    "change_card_checkitem_work": WorkTransitionOutput,
    "add_card_comment": CommentMutationOutput,
    "update_card_comment": CommentMutationOutput,
    "save_public_card_metadata": PublicMetadataOutput,
    "create_local_project_label": LabelCreationOutput,
    "use_global_project_label": GlobalLabelUseOutput,
    "change_card_label": CardLabelChangeOutput,
    "get_project_label_catalog": LabelCatalogOutput,
    "invite_project_members": MembershipChangeOutput,
    "add_project_people": MembershipChangeOutput,
    "set_card_people_and_labels": PeopleAndLabelsOutput,
    "set_card_relationships": RelationshipsOutput,
    "reconcile_card_checklist_projection": ChecklistReconcileOutput,
}
