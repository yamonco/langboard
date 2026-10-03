"""Typed modern command outputs; legacy handlers keep their domain contracts."""

from functools import wraps
from inspect import signature
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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


COMMAND_OUTPUTS = {
    "patch_card_description": DescriptionPatchOutput,
    "replace_card_description": DescriptionReplacementOutput,
    "assign_card_to_me": AssignmentOutput,
    "mark_notification_read": NotificationReadOutput,
    "mark_all_notifications_read": NotificationReadOutput,
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
