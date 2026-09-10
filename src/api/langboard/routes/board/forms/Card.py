from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.routing import BaseFormModel, form_model
from pydantic import Field


@form_model
class CreateCardForm(BaseFormModel):
    title: str = Field(..., title="Title of the card")
    project_column_uid: str = Field(..., title="UID of the column")
    description: EditorContentModel | None = Field(default=None, title="Description of the card")
    assign_users: list[str] | None = Field(default=None, title="List of user UIDs to assign to the card")


@form_model
class ChangeCardDetailsForm(BaseFormModel):
    title: str | None = Field(default=None, title="Title of the card")
    deadline_at: str | None = Field(default=None, title="Deadline of the card")
    description: EditorContentModel | None = Field(default=None, title="Description of the card")


@form_model
class UpdateCardLabelsForm(BaseFormModel):
    labels: list[str] = Field(..., title="List of label UIDs")


@form_model
class UpdateCardRelationshipsForm(BaseFormModel):
    is_parent: bool = Field(..., title="Is the card that is being updated the parent card?")
    relationships: list[tuple[str, str]] = Field(..., title="List of tuples of card UID and relationship type UID")


class CardGraphNewCardForm(BaseFormModel):
    client_ref: str = Field(..., title="Request-local reference beginning with new:")
    title: str = Field(..., title="Title of the new card")
    description: str | None = Field(default=None, title="Description of the new card")


class CardGraphEdgeForm(BaseFormModel):
    parent_ref: str = Field(..., title="Existing card UID or request-local new: reference")
    child_ref: str = Field(..., title="Existing card UID or request-local new: reference")
    relationship_type_uid: str = Field(..., title="Relationship type UID")


@form_model
class PatchCardGraphForm(BaseFormModel):
    new_cards: list[CardGraphNewCardForm] = Field(default_factory=list, max_length=7)
    add_edges: list[CardGraphEdgeForm] = Field(default_factory=list, max_length=25)
    remove_relationship_uids: list[str] = Field(default_factory=list, max_length=25)
