from langboard_shared.core.schema import TimeBasedPagination
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


class ActivityPagination(TimeBasedPagination):
    assignee_uid: str | None = None
    only_count: bool = False


@McpTool.add("user", description="Get activities for the current user.")
def get_current_user_activities(user: User, service: DomainService, limit: int = 50) -> dict:
    pagination = ActivityPagination(limit=limit)
    result = service.activity.get_api_list_by_user(user, pagination)
    if not result:
        return {"activities": [], "count_new_records": 0}
    activities, count_new_records, _ = result
    return {"activities": activities, "count_new_records": count_new_records}


@McpTool.add("user", description="Get activities for a project.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_activities(
    project_uid: str,
    service: DomainService,
    limit: int = 50,
    page: int = 1,
    refer_time: str | None = None,
) -> dict:
    pagination = ActivityPagination(page=page, limit=limit, refer_time=refer_time)
    result = service.activity.get_api_list_by_project(project_uid, pagination)
    if not result:
        return {
            "activities": [],
            "count_new_records": 0,
            "refer_time": str(pagination.refer_time),
        }
    activities, count_new_records, project = result
    return {
        "activities": activities,
        "count_new_records": count_new_records,
        "refer_time": str(pagination.refer_time),
        "project": {"uid": project.get_uid()},
    }


@McpTool.add("user", description="Get activities for a project column.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_column_activities(project_uid: str, column_uid: str, service: DomainService, limit: int = 50) -> dict:
    pagination = ActivityPagination(limit=limit)
    result = service.activity.get_api_list_by_column(project_uid, column_uid, pagination)
    if not result:
        return {"activities": [], "count_new_records": 0}
    activities, count_new_records, project, column = result
    return {
        "activities": activities,
        "count_new_records": count_new_records,
        "project": {"uid": project.get_uid()},
        "column": {"uid": column.get_uid()},
    }


@McpTool.add("user", description="Get activities for a card.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_activities(project_uid: str, card_uid: str, service: DomainService, limit: int = 50) -> dict:
    pagination = ActivityPagination(limit=limit)
    result = service.activity.get_api_list_by_card(project_uid, card_uid, pagination)
    if not result:
        return {"activities": [], "count_new_records": 0}
    activities, count_new_records, project, card = result
    return {
        "activities": activities,
        "count_new_records": count_new_records,
        "project": {"uid": project.get_uid()},
        "card": {"uid": card.get_uid()},
    }


@McpTool.add("user", description="Get activities for a wiki.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_wiki_activities(project_uid: str, wiki_uid: str, service: DomainService, limit: int = 50) -> dict:
    pagination = ActivityPagination(limit=limit)
    result = service.activity.get_api_list_by_wiki(project_uid, wiki_uid, pagination)
    if not result:
        return {"activities": [], "count_new_records": 0}
    activities, count_new_records, project, wiki = result
    return {
        "activities": activities,
        "count_new_records": count_new_records,
        "project": {"uid": project.get_uid()},
        "wiki": {"uid": wiki.get_uid()},
    }
