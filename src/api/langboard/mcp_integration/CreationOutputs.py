"""Native card creation and public cardification keep distinct result shapes."""

from datetime import datetime
from pydantic import Field
from .BoardOutputs import BoardCreationOutput
from .Outputs import CommandOutput
from .WorkOutputs import LabelOutput, PublicCardOutput, RelationshipOutput


class EditorBodyOutput(CommandOutput):
    content: str


class CreatorOutput(CommandOutput):
    uid: str
    type: str
    name: str
    avatar: str | None
    created_at: str


class NativeCardCreationOutput(CommandOutput):
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
    count_comment: int = Field(ge=0)
    member_uids: list[str]
    relationships: list[RelationshipOutput]
    labels: list[LabelOutput]
    creator: CreatorOutput | None
    has_description: bool
    completed: bool
    is_check_card: bool


class CreatedColumnOutput(CommandOutput):
    uid: str
    name: str


class LeftmostCardCreationOutput(CommandOutput):
    card: NativeCardCreationOutput
    column: CreatedColumnOutput


class CardifiedCardOutput(PublicCardOutput):
    member_uids: list[str] | None = None
    project_column_uid: str | None = None
    project_column_name: str | None = None
    order: int | None = Field(default=None, ge=0)
    deadline_at: datetime | str | None = None
    archived_at: datetime | str | None = None


class CardificationOutput(CommandOutput):
    card: CardifiedCardOutput
    source_checkitem_uid: str


CREATION_OUTPUTS = {
    "create_card": NativeCardCreationOutput,
    "create_card_in_leftmost_column": LeftmostCardCreationOutput,
    "cardify_card_checkitem": CardificationOutput,
    "provision_project": BoardCreationOutput,
}
