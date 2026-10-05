"""Native notification scope selection preserves user-owned canonical commands."""

from typing import Annotated, Literal
from pydantic import Field
from ..mcp_integration.Outputs import NotificationReadOutput
from ..mcp_integration.Tool import McpTool
from .CardActionsMcp import CardAction, Uid


class ReadOneNotification(CardAction):
    scope: Literal["one"]
    notification_uid: Uid


class ReadAllNotifications(CardAction):
    scope: Literal["all"]


NotificationReadChange = Annotated[ReadOneNotification | ReadAllNotifications, Field(discriminator="scope")]
NOTIFICATION_READ_COMMANDS = {"one": "mark_notification_read", "all": "mark_all_notifications_read"}


@McpTool.add(
    "user",
    description="Mark the explicitly requested notification scope read. one requires notification_uid; all forbids it and marks only the current user's visible unread notifications. Queries never mark notifications read.",
)
async def mark_notifications_read(change: NotificationReadChange) -> NotificationReadOutput:
    from ..mcp_integration.Server import McpServer

    command = NOTIFICATION_READ_COMMANDS[change.scope]
    metadata = McpTool.get_tool(command)
    if metadata is None:
        raise RuntimeError("Native notification command is unavailable")
    result = await McpServer._wrap_tool(command, metadata["handler"])(**change.model_dump(exclude={"scope"}))
    return NotificationReadOutput.model_validate(result)
