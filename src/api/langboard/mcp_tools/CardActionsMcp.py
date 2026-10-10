"""Client-independent card actions reuse authorized native commands."""

from typing import Annotated, Any, Literal
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.security import RoleFinder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..mcp_integration.RoleFilter import McpRoleFilter
from ..mcp_integration.Tool import McpTool


Text = Annotated[str, Field(min_length=1, max_length=500)]
Uid = Annotated[str, Field(min_length=1, max_length=80)]
Order = Annotated[int, Field(strict=True, ge=0)]


class CardAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssignCard(CardAction):
    action: Literal["assign"]
    assign_user_uids: list[Uid]


class LabelCard(CardAction):
    action: Literal["label"]
    label_uids: list[Uid]


class TitleCard(CardAction):
    action: Literal["title"]
    title: Text


class DeadlineCard(CardAction):
    action: Literal["deadline"]
    # The canonical command parses ISO time; an empty string explicitly clears it.
    deadline_at: str


class CompleteCard(CardAction):
    action: Literal["completion"]
    completed: Annotated[bool, Field(strict=True)]


class ReplaceCardDescription(CardAction):
    # Preserve reviewed body whitespace, including leading Markdown indentation.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    action: Literal["description_replace"]
    description: Annotated[str, Field(max_length=32000)]
    expected_revision: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]


class MoveCard(CardAction):
    action: Literal["move"]
    column_uid: Uid
    order: Order


class ArchiveCard(CardAction):
    action: Literal["archive"]


class DeleteCard(CardAction):
    action: Literal["delete"]


class UpdateCardAttachment(CardAction):
    action: Literal["attachment_update"]
    attachment_uid: Uid
    name: Text | None = None
    order: Order | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.order is None:
            raise ValueError("Attachment name or order is required")
        return self


class DeleteCardAttachment(CardAction):
    action: Literal["attachment_delete"]
    attachment_uid: Uid


class UploadCardAttachment(CardAction):
    action: Literal["attachment_upload"]
    filename: Text
    file_data_base64: str


CardChange = Annotated[
    AssignCard
    | LabelCard
    | TitleCard
    | DeadlineCard
    | CompleteCard
    | ReplaceCardDescription
    | MoveCard
    | ArchiveCard
    | DeleteCard
    | UpdateCardAttachment
    | DeleteCardAttachment
    | UploadCardAttachment,
    Field(discriminator="action"),
]

CARD_ACTION_COMMANDS = {
    "assign": "set_card_people_and_labels",
    "label": "set_card_people_and_labels",
    "title": "change_card_details",
    "deadline": "change_card_details",
    "completion": "set_card_completed",
    "description_replace": "replace_card_description",
    "move": "change_card_order_or_move_column",
    "archive": "archive_card",
    "delete": "delete_card",
    "attachment_update": "update_card_attachment",
    "attachment_delete": "delete_card_attachment",
    "attachment_upload": "upload_card_attachment",
}


@McpTool.add(
    description="Change one card field, lifecycle state or attachment. Pass one action-specific change; body replacement requires its reviewed revision. Labels select existing labels only."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
async def update_card(project_uid: str, card_uid: str, change: CardChange) -> dict[str, Any]:
    """Dispatch through the same per-command ACL, actor and service injection."""
    from ..mcp_integration.Server import McpServer

    command = CARD_ACTION_COMMANDS[change.action]
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native card command is unavailable")
    arguments = {
        "project_uid": project_uid,
        "card_uid": card_uid,
        **change.model_dump(exclude={"action"}, exclude_none=True),
    }
    return await McpServer._wrap_tool(command, metadata["handler"])(**arguments)
