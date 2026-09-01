from fastapi import Query
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    ApiPermission,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    collaborative_block,
    collaborative_edit,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import (
    Bot,
    Card,
    CardRelationship,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectBotSchedule,
    ProjectBotScope,
    ProjectColumn,
    ProjectColumnBotSchedule,
    ProjectColumnBotScope,
    ProjectLabel,
    ProjectRole,
    User,
)
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import InviteProjectMemberForm, ProjectInvitationForm


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.post(
    "/board/{project_uid}/available",
    tags=["Board"],
    description="Check if the project is available.",
    responses=OpenApiSchema().suc({"title": "string"}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def is_project_available(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    return JsonResponse(content={"title": project.title})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}",
    tags=["Board"],
    description="Get project details.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "project": (
                    Project,
                    {
                        "schema": {
                            "all_members": [User],
                            "invited_member_uids": "string[]",
                            "current_auth_role_actions": [ALL_GRANTED, ProjectRoleAction],
                            "labels": [ProjectLabel],
                        }
                    },
                ),
                "project_bot_scopes": [ProjectBotScope],
                "project_bot_schedules": [ProjectBotSchedule],
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project(
    project_uid: str, user_or_bot: User | Bot = Auth.scope("all"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.get_details(user_or_bot, project_uid, is_setting=False)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    project, response = result
    project_bot_scopes = service.project.get_api_bot_scope_list(project)
    project_bot_schedules = service.project.get_api_bot_schedule_list(project)
    if isinstance(user_or_bot, User):
        service.project.set_last_view(user_or_bot, project)
    return JsonResponse(
        content={
            "project": response,
            "project_bot_scopes": project_bot_scopes,
            "project_bot_schedules": project_bot_schedules,
        }
    )


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/assigned-users",
    tags=["Board"],
    description="Get project assigned users.",
    responses=OpenApiSchema().suc({"users": [User]}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_assigned_users(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    users = service.project.get_api_assigned_user_list(project)

    return JsonResponse(content={"users": users})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/member-candidates",
    tags=["Board"],
    description="Search project member invite candidates.",
    responses=OpenApiSchema().suc({"users": [User]}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def search_project_member_candidates(
    project_uid: str, query: str = "", user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    users = service.project.search_member_candidates(user, project_uid, query)
    if users is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse(content={"users": users})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/columns",
    tags=["Board"],
    description="Get project columns.",
    responses=(
        OpenApiSchema()
        .suc({"columns": [(ProjectColumn, {"schema": {"count": "integer"}})]})
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_columns(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    columns = service.project_column.get_api_list_by_project(project)
    return JsonResponse(content={"columns": columns})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/labels",
    tags=["Board"],
    description="Get project labels.",
    responses=OpenApiSchema().suc({"labels": [ProjectLabel]}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_labels(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    labels = service.project_label.get_api_list_by_project(project)
    return JsonResponse(content={"labels": labels})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/cards/context",
    tags=["Board"],
    description="Find bounded project card context.",
    responses=OpenApiSchema()
    .suc(
        {
            "cards": [
                {
                    "uid": "string",
                    "title": "string",
                    "description": {"content": "string"},
                    "project_column_name": "string",
                }
            ]
        }
    )
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2001)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_card_context(
    project_uid: str,
    input_value: str = Query(min_length=1, max_length=1000),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    return JsonResponse(content={"cards": service.card.search_context_by_project(project, input_value)})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/cards",
    tags=["Board"],
    description="Get project cards.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "cards": [
                    (
                        Card,
                        {
                            "schema": {
                                "project_column_name": "string",
                                "count_comment": "integer",
                                "member_uids": "string[]",
                                "relationships": [CardRelationship],
                                "labels": [ProjectLabel],
                            }
                        },
                    )
                ],
                "column_bot_scopes": [ProjectColumnBotScope],
                "column_bot_schedules": [ProjectColumnBotSchedule],
                "checklists": [Checklist],
                "global_relationships": [GlobalCardRelationshipType],
                "columns": [(ProjectColumn, {"schema": {"count": "integer"}})],
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_cards(project_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    global_relationships = service.app_setting.get_api_global_relationship_list()
    columns = service.project_column.get_api_list_by_project(project)
    cards = service.card.get_board_list(project)
    checklists = service.checklist.get_api_list_only_by_project(project)
    column_bot_scopes = service.project_column.get_api_bot_scopes_by_project(project)
    column_bot_schedules = service.project_column.get_api_bot_schedule_list_by_project(project, columns)

    column_names_by_uid = {col["uid"]: col["name"] for col in columns}
    for card in cards:
        card["project_column_name"] = column_names_by_uid.get(card["project_column_uid"], "")

    return JsonResponse(
        content={
            "cards": cards,
            "checklists": checklists,
            "global_relationships": global_relationships,
            "columns": columns,
            "column_bot_scopes": column_bot_scopes,
            "column_bot_schedules": column_bot_schedules,
        }
    )


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.BoardSettings, "{project_uid}", "members")
    )
)
@AppRouter.api.put(
    "/board/{project_uid}/assigned-users",
    tags=["Board"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def update_project_member(
    project_uid: str,
    form: InviteProjectMemberForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project.update_assigned_users(user, project_uid, form.emails)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.BoardSettings, "{project_uid}", "members")
    )
)
@AppRouter.api.delete(
    "/board/{project_uid}/unassign/{assignee_uid}",
    tags=["Board"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2005).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def unassign_project_assignee(
    project_uid: str, assignee_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.unassign_assignee(user, project_uid, assignee_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2005)

    return JsonResponse()


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/is-assigned/{assignee_uid}",
    tags=["Board"],
    description="Check if the user is assigned to the project.",
    responses=OpenApiSchema().suc({"result": "bool"}).auth().forbidden().err(404, ApiErrorCode.NF1004).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def is_project_assignee(
    project_uid: str, assignee_uid: str, service: DomainService = DomainService.scope()
) -> JsonResponse:
    target = service.user.get_by_id_like(assignee_uid)
    if not target:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    result, _ = service.project.is_assigned(target, project_uid)
    return JsonResponse(content={"result": result})


@AppRouter.api.post(
    "/project/invite/details/{token}",
    tags=["Board"],
    responses=(
        OpenApiSchema().suc({"project": {"title": "string"}}).auth().forbidden().err(404, ApiErrorCode.NF2002).get()
    ),
)
@AuthFilter.add("user")
def get_invited_project_title(
    token: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project_invitation.get_project_by_token(user, token)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2002)

    return JsonResponse(content={"project": {"title": project.title}})


@AppRouter.api.post(
    "/project/invite/accept",
    tags=["Board"],
    responses=OpenApiSchema().suc({"project_uid": "string"}).auth().forbidden().err(406, ApiErrorCode.NF2002).get(),
)
@AuthFilter.add("user")
def accept_project_invitation(
    form: ProjectInvitationForm, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project_invitation.accept(user, form.invitation_token)
    if not result:
        raise ApiException.NotAcceptable_406(ApiErrorCode.NF2002)

    return JsonResponse(content={"project_uid": result})


@AppRouter.api.post(
    "/project/invite/decline",
    tags=["Board"],
    responses=OpenApiSchema().auth().forbidden().err(406, ApiErrorCode.NF2002).get(),
)
@AuthFilter.add("user")
def decline_project_invitation(
    form: ProjectInvitationForm, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project_invitation.decline(user, form.invitation_token)
    if not result:
        raise ApiException.NotAcceptable_406(ApiErrorCode.NF2002)

    return JsonResponse()
