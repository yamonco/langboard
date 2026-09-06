"""Current-user notification and governed project-search MCP tools."""

from typing import Literal
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.services import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


NotificationTimeRange = Literal["3d", "7d", "1m", "all"]


@McpTool.add(
    "user",
    description="List unread notifications for the current user without marking them as read.",
)
def get_unread_notifications(
    user: User,
    service: DomainService,
    time_range: NotificationTimeRange = "all",
    page: int = 1,
    limit: int = 20,
) -> dict:
    """Return unread notifications that remain unread after this query."""

    if page < 1 or not 1 <= limit <= 50:
        raise ValueError("page must be positive and limit must be between 1 and 50")
    notifications, _, _ = service.notification.get_api_list(
        user,
        time_range,
        page,
        limit,
        unread_only=True,
    )
    accessible_projects, _ = service.project.get_api_list(user)
    accessible_project_uids = {project["uid"] for project in accessible_projects}
    notifications = [
        notification
        for notification in notifications
        if notification["type"] == NotificationType.ProjectInvited.value
        or notification.get("records", {}).get("project", {}).get("uid") in accessible_project_uids
    ]
    return {
        "notifications": notifications,
        "returned_count": len(notifications),
    }


@McpTool.add(
    "user",
    description="Mark one notification owned by the current user as read after explicit user approval.",
)
def mark_notification_read(notification_uid: str, user: User, service: DomainService) -> dict[str, bool]:
    """Mark one owned notification as read."""

    if not service.notification.read(user, notification_uid):
        raise ValueError("Notification not found")
    return {"read": True}


@McpTool.add(
    "user",
    description="Mark every unread notification for the current user as read after explicit user approval.",
)
def mark_all_notifications_read(user: User, service: DomainService) -> dict[str, bool]:
    """Mark every notification owned by the current user as read."""

    service.notification.read_all(user)
    return {"read": True}


@McpTool.add(description="Search cards inside one readable project without changing view or read state.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def search_project_cards(project_uid: str, query: str, service: DomainService) -> dict:
    """Search bounded card context through the native project-scoped query."""

    normalized_query = query.strip()
    if not 1 <= len(normalized_query) <= 1000:
        raise ValueError("query must contain between 1 and 1000 characters")
    return {"cards": service.card.search_context_by_project(project_uid, normalized_query)}
