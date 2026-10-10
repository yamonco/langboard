"""Native checklist actions retain canonical validation and authorization."""

from typing import Annotated, Any, Literal
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.security import RoleFinder
from pydantic import Field, StrictBool, model_validator
from ..mcp_integration.RoleFilter import McpRoleFilter
from ..mcp_integration.Tool import McpTool
from .CardActionsMcp import CardAction, Text, Uid


class CreateList(CardAction):
    action: Literal["create_list"]
    title: Text


class AddItem(CardAction):
    action: Literal["add_item"]
    checklist_uid: Uid
    title: Text


class UpdateList(CardAction):
    action: Literal["update_list"]
    checklist_uid: Uid
    title: Text | None = None
    is_checked: StrictBool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.is_checked is None:
            raise ValueError("Checklist title or checked state is required")
        return self


class DeleteList(CardAction):
    action: Literal["delete_list"]
    checklist_uid: Uid


class SetCompleted(CardAction):
    action: Literal["set_completed"]
    checkitem_uid: Uid
    is_checked: StrictBool


class UpdateItem(CardAction):
    action: Literal["update_item"]
    checkitem_uid: Uid
    title: Text | None = None
    deadline_at: str | None = None
    is_checked: StrictBool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.deadline_at is None and self.is_checked is None:
            raise ValueError("Checkitem title, deadline or checked state is required")
        return self


class DeleteItem(CardAction):
    action: Literal["delete_item"]
    checkitem_uid: Uid


class PromoteItem(CardAction):
    action: Literal["promote"]
    checkitem_uid: Uid
    project_column_uid: Uid


ChecklistChange = Annotated[
    CreateList | AddItem | UpdateList | DeleteList | SetCompleted | UpdateItem | DeleteItem | PromoteItem,
    Field(discriminator="action"),
]

CHECKLIST_ACTION_COMMANDS = {
    "create_list": "create_card_checklist",
    "add_item": "create_card_checkitem",
    "update_list": "update_card_checklist",
    "delete_list": "delete_card_checklist",
    "set_completed": "update_card_checkitem",
    "update_item": "update_card_checkitem",
    "delete_item": "delete_card_checkitem",
    "promote": "cardify_card_checkitem",
}


@McpTool.add(
    description="Change one native checklist or item with one action-specific change. Completion is explicit; promotion requires an active column. After ambiguous promotion, read the item's cardified_card link before retrying."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
async def change_card_checklist(project_uid: str, card_uid: str, change: ChecklistChange) -> dict[str, Any]:
    """Reuse each command's ACL, ancestry validation and actor/service injection."""
    from ..mcp_integration.Server import McpServer

    command = CHECKLIST_ACTION_COMMANDS[change.action]
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native checklist command is unavailable")
    arguments = {
        "project_uid": project_uid,
        "card_uid": card_uid,
        **change.model_dump(exclude={"action"}, exclude_none=True),
    }
    return await McpServer._wrap_tool(command, metadata["handler"])(**arguments)
