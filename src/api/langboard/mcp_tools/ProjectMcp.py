from re import fullmatch
from langboard_shared.domain.models import Bot, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.Env import Env
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


def create_template_project(
    title: str,
    description: str | None,
    project_type: str,
    user: User,
    service: DomainService,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict:
    """Use the project owner service and return the public template projection."""

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Project title is required")
    if template_name is not None:
        if not isinstance(template_name, str) or not template_name.strip():
            raise ValueError("Template name is required")
        template_name = template_name.strip()
    project, columns, template = service.project_template.create_project(
        user, title.strip(), description, project_type, template_name, infer_template_prefix
    )
    uid = project.get_uid()
    return {
        "project": {
            "uid": uid,
            "title": project.title,
            "project_type": project.project_type,
            "url": f"{Env.PUBLIC_UI_URL}/board/{uid}",
            "template": template.name,
        },
        "columns": [{**column.api_response(), "count": 0} for column in columns],
    }


@McpTool.add("user", description="Create a new project with an optional named workflow template.")
def create_project(
    title: str,
    description: str | None,
    project_type: str,
    user: User,
    service: DomainService,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict:
    result = create_template_project(
        title, description, project_type, user, service, template_name, infer_template_prefix
    )
    project = result["project"]
    return {"project_uid": project["uid"]}


@McpTool.add("user", description="Compatibility entry for template-backed board creation.")
def create_project_board(
    title: str,
    user: User,
    service: DomainService,
    description: str | None = None,
    template_name: str | None = None,
    infer_template_prefix: bool = False,
) -> dict:
    return create_template_project(title, description, "Other", user, service, template_name, infer_template_prefix)


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


def _active_column_order(project_uid: str, service: DomainService) -> list[dict]:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ValueError("Project not found")
    return [column for column in service.project_column.get_api_list_by_project(project) if not column["is_archive"]]


def _column_target_order(
    columns: list[dict],
    *,
    position: str | None,
    after_column_uid: str | None,
    before_column_uid: str | None,
    moving_uid: str | None = None,
) -> int:
    selectors = sum(value is not None for value in (position, after_column_uid, before_column_uid))
    if selectors > 1 or position not in (None, "leftmost", "rightmost"):
        raise ValueError("Choose one valid column position")
    uids = [column["uid"] for column in columns if column["uid"] != moving_uid]
    if position == "leftmost":
        return 0
    if after_column_uid is not None:
        if after_column_uid not in uids:
            raise ValueError("After column not found in project")
        return uids.index(after_column_uid) + 1
    if before_column_uid is not None:
        if before_column_uid not in uids:
            raise ValueError("Before column not found in project")
        return uids.index(before_column_uid)
    return len(uids)


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


def _compact_member(member: User | dict[str, object]) -> dict[str, str] | None:
    """Return safe display fields from either a native user or its API projection."""

    if isinstance(member, dict):
        if member.get("type") != User.USER_TYPE:
            return None
        uid = member.get("uid")
        firstname = member.get("firstname")
        lastname = member.get("lastname")
        username = member.get("username")
        if not all(isinstance(value, str) for value in (uid, firstname, lastname, username)):
            return None
        return {"uid": uid, "firstname": firstname, "lastname": lastname, "username": username}

    return {
        "uid": member.get_uid(),
        "firstname": member.firstname,
        "lastname": member.lastname,
        "username": member.username,
    }


@McpTool.add(description="Search existing people who can be added to a project without exposing email addresses.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def search_project_people(
    project_uid: str, query: str, user_or_bot: User | Bot, service: DomainService
) -> dict[str, list[dict[str, str]]]:
    """Find bounded, permission-scoped people for one project updater."""

    if not isinstance(user_or_bot, User):
        raise ValueError("Only users can search project people")
    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise ValueError("Use at least two characters to search people")
    candidates = service.project.search_member_candidates(user_or_bot, project_uid, normalized_query)
    if candidates is None:
        raise ValueError("Project not found")
    return {"items": [compact for candidate in candidates if (compact := _compact_member(candidate)) is not None]}


@McpTool.add(description="Add existing people to a project without replacing current members.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def add_project_people(
    project_uid: str, member_uids: list[str], user_or_bot: User | Bot, service: DomainService
) -> dict[str, int | str]:
    """Immediately add up to ten known people without invitations or member replacement."""

    if not isinstance(user_or_bot, User):
        raise ValueError("Only users can add project people")
    if not 1 <= len(member_uids) <= 10:
        raise ValueError("Provide between 1 and 10 people")
    selected_uids = list(dict.fromkeys(member_uids))
    selected_people = [service.user.get_by_id_like(member_uid) for member_uid in selected_uids]
    if any(person is None or person.deleted_at is not None for person in selected_people):
        raise ValueError("One or more selected people no longer exist")
    result = service.project.add_existing_assigned_users(
        user_or_bot, project_uid, [person for person in selected_people if person is not None]
    )
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
def create_column(
    project_uid: str,
    user_or_bot: User | Bot,
    name: str,
    service: DomainService,
    description: str = "",
    position: str | None = None,
    after_column_uid: str | None = None,
    before_column_uid: str | None = None,
) -> dict:
    if not name.strip() or len(name) > 300:
        raise ValueError("Column name must contain 1-300 characters")
    columns = _active_column_order(project_uid, service)
    order = _column_target_order(
        columns, position=position, after_column_uid=after_column_uid, before_column_uid=before_column_uid
    )
    column = service.project_column.create(user_or_bot, project_uid, name.strip(), description=description)
    if not column:
        raise ValueError("Failed to create")
    if order < len(columns):
        service.project_column.change_order(project_uid, column, order)
    return next(item for item in _active_column_order(project_uid, service) if item["uid"] == column.get_uid())


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
    order: int | None,
    service: DomainService,
    position: str | None = None,
    after_column_uid: str | None = None,
    before_column_uid: str | None = None,
) -> dict:
    columns = _active_column_order(project_uid, service)
    if column_uid not in {column["uid"] for column in columns}:
        raise ValueError("Column not found in project")
    if order is not None and any(value is not None for value in (position, after_column_uid, before_column_uid)):
        raise ValueError("Choose order or a relative position")
    if order is None:
        order = _column_target_order(
            columns,
            position=position,
            after_column_uid=after_column_uid,
            before_column_uid=before_column_uid,
            moving_uid=column_uid,
        )
    if isinstance(order, bool) or order < 0 or order >= len(columns):
        raise ValueError("Column order must be a non-negative integer")
    result = service.project_column.change_order(project_uid, column_uid, order)
    if not result:
        raise ValueError("Failed")
    return {"column_uid": column_uid, "columns": _active_column_order(project_uid, service)}


@McpTool.add(description="Delete a column from a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def delete_column(project_uid: str, column_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    result = service.project_column.delete(user_or_bot, project_uid, column_uid)
    if not result:
        raise ValueError("Failed")
    return {"message": "Deleted"}
