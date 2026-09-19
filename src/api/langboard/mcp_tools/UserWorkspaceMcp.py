"""Current-user notification and governed project-search MCP tools."""

from datetime import datetime, timedelta
from typing import Literal
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.services import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


NotificationTimeRange = Literal["3d", "7d", "1m", "all"]
MyWorkPurpose = Literal["assigned", "mentioned", "due_soon", "overdue", "created"]


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
def search_project_cards(
    project_uid: str,
    query: str,
    service: DomainService,
    date_field: Literal["created_at", "updated_at"] = "updated_at",
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Search bounded card context through the native project-scoped query."""

    normalized_query = query.strip()
    if not 1 <= len(normalized_query) <= 1000:
        raise ValueError("query must contain between 1 and 1000 characters")

    def parse_bound(value: str | None) -> SafeDateTime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Date bounds must include a timezone")
        return SafeDateTime.fromisoformat(value)

    lower, upper = parse_bound(since), parse_bound(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("since must be earlier than until")
    return {
        "cards": service.card.search_context_by_project(
            project_uid,
            normalized_query,
            date_field=date_field,
            since=lower,
            until=upper,
        )
    }


@McpTool.add(
    "user",
    description=(
        "List the current user's active work across readable projects. Results are deduplicated and "
        "independent of notification read state."
    ),
)
def get_my_work_cards(
    user: User,
    service: DomainService,
    purposes: list[MyWorkPurpose] | None = None,
    project_uid: str | None = None,
    date_field: Literal["created_at", "updated_at"] = "updated_at",
    since: str | None = None,
    until: str | None = None,
    due_within_days: int = 7,
    limit: int = 20,
) -> dict:
    """Return a compact My Work queue filtered by current-user relationships."""

    selected = set(purposes or ["assigned", "mentioned", "due_soon", "overdue", "created"])
    if not selected <= {"assigned", "mentioned", "due_soon", "overdue", "created"}:
        raise ValueError("purposes contain an unsupported value")
    if not 1 <= due_within_days <= 30 or not 1 <= limit <= 50:
        raise ValueError("due_within_days must be 1-30 and limit must be 1-50")

    def parse_bound(value: str | None) -> SafeDateTime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Date bounds must include a timezone")
        return SafeDateTime.fromisoformat(value)

    lower, upper = parse_bound(since), parse_bound(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("since must be earlier than until")

    accessible_projects, _ = service.project.get_api_list(user)
    if project_uid is not None:
        accessible_projects = [project for project in accessible_projects if project["uid"] == project_uid]
        if not accessible_projects:
            raise ValueError("Project not found or not readable")

    mentioned_card_ids = service.notification.get_mentioned_card_ids(user) if "mentioned" in selected else []
    due_before = SafeDateTime.now() + timedelta(days=due_within_days)
    cards = service.card.get_my_work_cards(
        user,
        accessible_projects,
        selected,
        mentioned_card_ids,
        due_before,
        date_field,
        lower,
        upper,
        limit,
    )
    return {
        "cards": cards,
        "returned_count": len(cards),
    }
