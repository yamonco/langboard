from re import fullmatch
from langboard_shared.domain.models import Bot, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


def _normalize_invitation_emails(emails: list[str]) -> list[str]:
    """Validate, normalize, and bound one additive invitation request."""

    if not 1 <= len(emails) <= 10:
        raise ValueError("Provide between 1 and 10 email addresses")
    normalized = list(dict.fromkeys(email.strip().casefold() for email in emails))
    if any(fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None for email in normalized):
        raise ValueError("Invalid email address")
    return normalized


@McpTool.add("user", description="Get starred projects for the current user.")
def get_starred_projects(user: User, service: DomainService) -> dict:
    projects = service.project.get_api_starred_project_list(user)
    return {"projects": projects}


@McpTool.add("user", description="Get all projects for the current user.")
def get_projects(user: User, service: DomainService) -> dict:
    projects, _ = service.project.get_api_list(user)
    return {"projects": projects}


@McpTool.add("user", description="Toggle star status for a project.")
def toggle_star_project(project_uid: str, user: User, service: DomainService) -> dict:
    result = service.project.toggle_star(user, project_uid)
    if not result:
        raise ValueError("Failed")
    return {"message": "Toggled"}


@McpTool.add("user", description="Create a new project.")
def create_project(title: str, description: str | None, project_type: str, user: User, service: DomainService) -> dict:
    project = service.project.create(user, title, description, project_type)
    return {"project_uid": project.get_uid()}


@McpTool.add(description="Check if the project is available.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def is_project_available(project_uid: str, service: DomainService) -> dict:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    return {"title": p.title}


@McpTool.add(description="Get project details.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project(project_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    result = service.project.get_details(user_or_bot, project_uid, False)
    if not result:
        raise ValueError("Project not found")
    project, response = result
    bot_scopes = service.project.get_api_bot_scope_list(project)
    bot_schedules = service.project.get_api_bot_schedule_list(project)
    if isinstance(user_or_bot, User):
        service.project.set_last_view(user_or_bot, project)
    return {"project": response, "project_bot_scopes": bot_scopes, "project_bot_schedules": bot_schedules}


@McpTool.add(description="Get project assigned users.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_assigned_users(project_uid: str, service: DomainService) -> list[dict]:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    return service.project.get_api_assigned_user_list(p)


@McpTool.add(description="Get project columns.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_columns(project_uid: str, service: DomainService) -> list[dict]:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    return service.project_column.get_api_list_by_project(p)


@McpTool.add(description="Get project labels.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_labels(project_uid: str, service: DomainService) -> list[dict]:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    return service.project_label.get_api_list_by_project(p)


@McpTool.add(description="Get project checklists.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_checklists(project_uid: str, service: DomainService) -> dict:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    checklists = service.checklist.get_api_list_only_by_project(p)
    return {"checklists": checklists}


@McpTool.add(description="Get global card relationship types.")
def get_global_relationships(service: DomainService) -> dict:
    global_rels = service.app_setting.get_api_global_relationship_list()
    return {"global_relationships": global_rels}


@McpTool.add(description="Get bot scopes for all columns in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_column_bot_scopes(project_uid: str, service: DomainService) -> dict:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    col_bot_scopes = service.project_column.get_api_bot_scopes_by_project(p)
    return {"column_bot_scopes": col_bot_scopes}


@McpTool.add(description="Get bot schedules for all columns in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_column_bot_schedules(project_uid: str, service: DomainService) -> dict:
    p = service.project.get_by_id_like(project_uid)
    if not p:
        raise ValueError("Project not found")
    columns = service.project_column.get_api_list_by_project([p])
    col_bot_schedules = service.project_column.get_api_bot_schedule_list_by_project(p, columns)
    return {"column_bot_schedules": col_bot_schedules}


@McpTool.add(description="Update project members by inviting users via email.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def update_project_members(
    project_uid: str, user_or_bot: User | Bot, emails: list[str], service: DomainService
) -> dict:
    if not isinstance(user_or_bot, User):
        raise ValueError("Only users can access this endpoint")
    result = service.project.update_assigned_users(user_or_bot, project_uid, emails)
    if result is None:
        raise ValueError("Failed to update")
    return {"message": "Updated"}


@McpTool.add(description="Invite up to 10 project members without removing existing members.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def invite_project_members(
    project_uid: str, user_or_bot: User | Bot, emails: list[str], service: DomainService
) -> dict[str, int | str]:
    """Add project invitations idempotently and return no recipient data."""

    if not isinstance(user_or_bot, User):
        raise ValueError("Only users can access this endpoint")
    result = service.project.invite_assigned_users(user_or_bot, project_uid, _normalize_invitation_emails(emails))
    if result is None:
        raise ValueError("Project not found")
    return result


@McpTool.add(description="Unassign a member from a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def unassign_project_member(
    project_uid: str, assignee_uid: str, user_or_bot: User | Bot, service: DomainService
) -> dict:
    if not isinstance(user_or_bot, User):
        raise ValueError("Only users can access this endpoint")
    result = service.project.unassign_assignee(user_or_bot, project_uid, assignee_uid)
    if not result:
        raise ValueError("Failed to unassign")
    return {"message": "Unassigned"}


@McpTool.add(description="Check if a user is assigned to a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def is_project_assignee(project_uid: str, assignee_uid: str, service: DomainService) -> dict[str, bool]:
    target = service.user.get_by_id_like(assignee_uid)
    if not target:
        raise ValueError("User not found")
    result, _ = service.project.is_assigned(target, project_uid)
    return {"result": result}


@McpTool.add(description="Create a new column in a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def create_column(project_uid: str, user_or_bot: User | Bot, name: str, service: DomainService) -> dict:
    column = service.project_column.create(user_or_bot, project_uid, name)
    if not column:
        raise ValueError("Failed to create")
    return {**column.api_response(), "count": 0}


@McpTool.add(description="Change column name.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def change_column_name(
    project_uid: str, column_uid: str, user_or_bot: User | Bot, name: str, service: DomainService
) -> dict:
    result = service.project_column.change_name(user_or_bot, project_uid, column_uid, name)
    if not result:
        raise ValueError("Failed")
    return {"name": name}


@McpTool.add(description="Change column order.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def change_column_order(
    project_uid: str,
    column_uid: str,
    order: int,
    service: DomainService,
) -> dict:
    if isinstance(order, bool) or order < 0:
        raise ValueError("Column order must be a non-negative integer")
    result = service.project_column.change_order(project_uid, column_uid, order)
    if not result:
        raise ValueError("Failed")
    return {"message": "Order changed"}


@McpTool.add(description="Delete a column from a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def delete_column(project_uid: str, column_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    result = service.project_column.delete(user_or_bot, project_uid, column_uid)
    if not result:
        raise ValueError("Failed")
    return {"message": "Deleted"}
