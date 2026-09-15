from typing import Any, Literal
from fastapi import Depends, Query
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import InfiniteRefreshableList, OpenApiSchema
from langboard_shared.domain.models import Bot, ProjectRole, ProjectWikiActivity, User, UserActivity
from langboard_shared.domain.models.bases import BaseActivityModel
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .ActivityForm import ActivityPagination


USER_ACTIVITY_SCHEMA = InfiniteRefreshableList.api_schema(
    (
        UserActivity,
        {
            "schema": {
                "refer?": BaseActivityModel,
                "references?": {"refer_type": "project", "<refer table>": "object"},
            }
        },
    )
)


@AppRouter.api.get("/activity/user/{user_uid}/shared", tags=["Activity"], response_model=None)
@AuthFilter.add("user")
def get_shared_user_activities(
    user_uid: str,
    pagination: ActivityPagination = Depends(),
    activity_uid: str | None = None,
    scope: Literal["project", "wiki"] | None = None,
    offset: int = Query(default=0, ge=0),
    max_chars: int = Query(default=4000, ge=1, le=8000),
    project_uid: str | None = None,
    since: str | None = None,
    until: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    try:
        result = service.activity.get_shared_user_activities(
            user, user_uid, pagination, activity_uid, scope, offset, max_chars, project_uid, since, until
        )
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    return JsonResponse(content=result)


def _create_project_activity_schema(
    activity: type[BaseActivityModel] = BaseActivityModel, references: dict | None = None
) -> dict[str, Any]:
    return InfiniteRefreshableList.api_schema(
        activity,
        {
            "references": {
                "project": {"uid": "string"},
                **(references or {}),
            }
        },
    )


@AppRouter.api.get(
    "/activity/user", tags=["Activity"], responses=OpenApiSchema().suc(USER_ACTIVITY_SCHEMA).auth().forbidden().get()
)
@AuthFilter.add("user")
def get_current_user_activities(
    pagination: ActivityPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if pagination.only_count:
        result = service.activity.get_api_list_by_user(user, pagination, only_count=True)
        return JsonResponse(content={"count_new_records": result or 0})

    result = service.activity.get_api_list_by_user(user, pagination)
    if not result:
        return JsonResponse(content=InfiniteRefreshableList())
    activities, count_new_records, _ = result
    return JsonResponse(content=InfiniteRefreshableList(records=activities, count_new_records=count_new_records))


@AppRouter.api.get(
    "/activity/project/{project_uid}",
    tags=["Activity"],
    responses=OpenApiSchema().suc(_create_project_activity_schema()).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_activities(
    project_uid: str,
    pagination: ActivityPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    assignee = service.activity.get_user_or_bot(pagination.assignee_uid) if pagination.assignee_uid else None
    if not _can_view_other_assignee_activities(project_uid, user, assignee, service):
        return JsonResponse(content=InfiniteRefreshableList())

    if pagination.only_count:
        result = service.activity.get_api_list_by_project(
            project_uid, pagination, only_count=True, assignee=pagination.assignee_uid
        )
        return JsonResponse(content=InfiniteRefreshableList(count_new_records=result or 0))

    result = service.activity.get_api_list_by_project(project_uid, pagination, assignee=pagination.assignee_uid)
    if not result:
        return JsonResponse(content=InfiniteRefreshableList())
    activities, count_new_records, project = result
    return JsonResponse(
        content={
            **InfiniteRefreshableList(records=activities, count_new_records=count_new_records).model_dump(),
            "references": {"project": {"uid": project.get_uid()}},
        }
    )


@AppRouter.api.get(
    "/activity/project/{project_uid}/column/{column_uid}",
    tags=["Activity"],
    responses=(
        OpenApiSchema()
        .suc(_create_project_activity_schema(references={"project_column": {"uid": "string"}}))
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_column_activities(
    project_uid: str,
    column_uid: str,
    pagination: ActivityPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    assignee = service.activity.get_user_or_bot(pagination.assignee_uid) if pagination.assignee_uid else None
    if not _can_view_other_assignee_activities(project_uid, user, assignee, service):
        return JsonResponse(content=InfiniteRefreshableList())

    if pagination.only_count:
        result = service.activity.get_api_list_by_column(
            project_uid, column_uid, pagination, only_count=True, assignee=assignee
        )
        return JsonResponse(content=InfiniteRefreshableList(count_new_records=result or 0))

    result = service.activity.get_api_list_by_column(project_uid, column_uid, pagination, assignee=assignee)
    if not result:
        return JsonResponse(content=InfiniteRefreshableList())
    activities, count_new_records, project, column = result
    return JsonResponse(
        content={
            **InfiniteRefreshableList(records=activities, count_new_records=count_new_records).model_dump(),
            "references": {
                "project": {
                    "uid": project.get_uid(),
                },
                "project_column": {
                    "uid": column.get_uid(),
                },
            },
        }
    )


@AppRouter.api.get(
    "/activity/project/{project_uid}/card/{card_uid}",
    tags=["Activity"],
    responses=(
        OpenApiSchema()
        .suc(_create_project_activity_schema(references={"card": {"uid": "string"}}))
        .auth()
        .forbidden()
        .get()
    ),
)
@AppRouter.schema(query=ActivityPagination, permission=ApiPermission.Read)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_card_activities(
    project_uid: str,
    card_uid: str,
    pagination: ActivityPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    assignee = service.activity.get_user_or_bot(pagination.assignee_uid) if pagination.assignee_uid else None
    if not _can_view_other_assignee_activities(project_uid, user, assignee, service):
        return JsonResponse(content=InfiniteRefreshableList())

    if pagination.only_count:
        result = service.activity.get_api_list_by_card(
            project_uid, card_uid, pagination, only_count=True, assignee=assignee
        )
        return JsonResponse(content=InfiniteRefreshableList(count_new_records=result or 0))

    result = service.activity.get_api_list_by_card(project_uid, card_uid, pagination, assignee=assignee)
    if not result:
        return JsonResponse(content=InfiniteRefreshableList())
    activities, count_new_records, project, card = result
    return JsonResponse(
        content={
            **InfiniteRefreshableList(records=activities, count_new_records=count_new_records).model_dump(),
            "references": {
                "project": {
                    "uid": project.get_uid(),
                },
                "card": {
                    "uid": card.get_uid(),
                },
            },
        }
    )


@AppRouter.api.get(
    "/activity/project/{project_uid}/wiki/{wiki_uid}",
    tags=["Activity"],
    responses=(
        OpenApiSchema()
        .suc(_create_project_activity_schema(ProjectWikiActivity, {"project_wiki": {"uid": "string"}}))
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_wiki_activities(
    project_uid: str,
    wiki_uid: str,
    pagination: ActivityPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    assignee = service.activity.get_user_or_bot(pagination.assignee_uid) if pagination.assignee_uid else None
    if not _can_view_other_assignee_activities(project_uid, user, assignee, service):
        return JsonResponse(content=InfiniteRefreshableList())

    if pagination.only_count:
        result = service.activity.get_api_list_by_wiki(
            project_uid, wiki_uid, pagination, only_count=True, assignee=assignee
        )
        return JsonResponse(content=InfiniteRefreshableList(count_new_records=result or 0))

    result = service.activity.get_api_list_by_wiki(project_uid, wiki_uid, pagination, assignee=assignee)
    if not result:
        return JsonResponse(content=InfiniteRefreshableList())
    activities, count_new_records, project, project_wiki = result
    return JsonResponse(
        content={
            **InfiniteRefreshableList(records=activities, count_new_records=count_new_records).model_dump(),
            "references": {
                "project": {
                    "uid": project.get_uid(),
                },
                "project_wiki": {
                    "uid": project_wiki.get_uid(),
                },
            },
        }
    )


def _can_view_other_assignee_activities(
    project_uid: str, user: User, assignee: User | Bot | None, service: DomainService
) -> bool:
    return (
        not assignee
        or user.is_admin
        or isinstance(assignee, Bot)
        or service.project.are_users_related(user, assignee, project_uid)
    )
