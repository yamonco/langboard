"""Typed modern command outputs; legacy handlers keep their domain contracts."""

from functools import wraps
from inspect import signature
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("changed", "read", "deleted", "moved", "is_reacted", mode="before", check_fields=False)
    @classmethod
    def require_boolean(cls, value):
        # Pydantic Literal[True] alone accepts the integer 1 even with strict=True.
        if type(value) is not bool:
            raise ValueError("Expected a boolean")
        return value


class DescriptionReplacementOutput(CommandOutput):
    changed: Literal[True]
    description_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    description_chars: int = Field(ge=0)


class DescriptionPatchOutput(DescriptionReplacementOutput):
    applied_edits: int = Field(ge=1)


class AssignmentOutput(CommandOutput):
    card_uid: str
    assigned_user_uid: str
    changed: bool


class NotificationReadOutput(CommandOutput):
    read: Literal[True]


class MessageOutput(CommandOutput):
    message: str


class DeletedOutput(CommandOutput):
    deleted: Literal[True]


class MovedOutput(CommandOutput):
    moved: Literal[True]


class ReactionOutput(CommandOutput):
    is_reacted: bool


class ColumnNameOutput(CommandOutput):
    name: str


class ProjectCreationOutput(CommandOutput):
    project_uid: str


class WikiCreationOutput(CommandOutput):
    wiki_uid: str
    title: str
    visibility: Literal["project"]


class WikiRevisionOutput(CommandOutput):
    wiki_uid: str
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


COMMAND_OUTPUTS = {
    "patch_card_description": DescriptionPatchOutput,
    "replace_card_description": DescriptionReplacementOutput,
    "assign_card_to_me": AssignmentOutput,
    "mark_notification_read": NotificationReadOutput,
    "mark_all_notifications_read": NotificationReadOutput,
    "create_project": ProjectCreationOutput,
    "create_project_wiki": WikiCreationOutput,
    "append_wiki_content": WikiRevisionOutput,
    "patch_wiki_content": WikiRevisionOutput,
    "replace_wiki_content": WikiRevisionOutput,
    "change_column_name": ColumnNameOutput,
    "toggle_card_comment_reaction": ReactionOutput,
    "move_card_content_block": MovedOutput,
    **dict.fromkeys(
        {
            "delete_project_wiki",
            "delete_card_comment",
            "delete_card_checklist",
            "delete_card_checkitem",
            "delete_card_attachment",
            "delete_public_card_metadata",
            "delete_card_content_block",
        },
        DeletedOutput,
    ),
    **dict.fromkeys(
        {
            "toggle_star_project",
            "update_project_members",
            "unassign_project_member",
            "delete_column",
            "archive_card",
            "delete_card",
            "change_card_order_or_move_column",
            "save_card_metadata",
            "delete_card_metadata",
            "save_wiki_metadata",
            "delete_wiki_metadata",
        },
        MessageOutput,
    ),
}


def with_typed_output(name, handler):
    """Use native FastMCP return annotations and validate after domain execution."""
    model = COMMAND_OUTPUTS.get(name)
    if model is None:
        return handler

    @wraps(handler)
    async def validated(**kwargs):
        return model.model_validate(await handler(**kwargs))

    validated.__signature__ = signature(handler).replace(return_annotation=model)
    return validated
