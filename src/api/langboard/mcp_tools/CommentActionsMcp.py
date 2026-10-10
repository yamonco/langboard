"""Native comment actions reuse canonical ownership and reaction commands."""

from typing import Annotated, Literal
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.security import RoleFinder
from pydantic import Field, model_serializer, model_validator
from ..mcp_integration.Outputs import CommandOutput, DeletedOutput, ReactionOutput
from ..mcp_integration.RoleFilter import McpRoleFilter
from ..mcp_integration.Tool import McpTool
from ..mcp_integration.WorkOutputs import CommentMutationOutput, CommentOutput
from .CardActionsMcp import CardAction, Uid
from .CardMcp import CardCommentReactionType


class AddComment(CardAction):
    action: Literal["add"]
    content: Annotated[str, Field(min_length=1)]


class EditComment(AddComment):
    action: Literal["edit"]
    comment_uid: Uid


class DeleteComment(CardAction):
    action: Literal["delete"]
    comment_uid: Uid


class ReactComment(CardAction):
    action: Literal["react"]
    comment_uid: Uid
    reaction: CardCommentReactionType


CommentChange = Annotated[AddComment | EditComment | DeleteComment | ReactComment, Field(discriminator="action")]
COMMENT_ACTION_COMMANDS = {
    "add": "add_card_comment",
    "edit": "update_card_comment",
    "delete": "delete_card_comment",
    "react": "toggle_card_comment_reaction",
}


class CommentActionOutput(CommandOutput):
    comment: CommentOutput | None = None
    deleted: Literal[True] | None = None
    is_reacted: bool | None = None

    @model_validator(mode="after")
    def require_one_result(self):
        if sum(value is not None for value in (self.comment, self.deleted, self.is_reacted)) != 1:
            raise ValueError("Expected exactly one comment action result")
        return self

    @model_serializer(mode="wrap")
    def serialize_result(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


@McpTool.add(
    description="Add, edit, delete or toggle a comment reaction with one action-specific change. Edit/delete require ownership; reactions do not approve workflows."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
async def change_card_comment(project_uid: str, card_uid: str, change: CommentChange) -> CommentActionOutput:
    from ..mcp_integration.Server import McpServer

    command = COMMENT_ACTION_COMMANDS[change.action]
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native comment command is unavailable")
    result = await McpServer._wrap_tool(command, metadata["handler"])(
        project_uid=project_uid,
        card_uid=card_uid,
        **change.model_dump(exclude={"action"}),
    )
    output = (
        DeletedOutput
        if change.action == "delete"
        else ReactionOutput
        if change.action == "react"
        else CommentMutationOutput
    )
    return CommentActionOutput.model_validate(output.model_validate(result).model_dump())
