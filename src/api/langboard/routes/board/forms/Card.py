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


@form_model
class CardifySelectionForm(BaseFormModel):
    selected_markdown: str = Field(..., min_length=3, max_length=32000, title="Selected body markdown to extract into a child card")
