from fastapi import status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.utils.Converter import convert_python_data
from langboard_shared.domain.models import (
    Bot,
    Card,
    ChatTemplate,
    InternalBot,
    Project,
    ProjectAssignedInternalBot,
    ProjectColumn,
    ProjectLabel,
    ProjectRole,
    User,
)
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import (
    ChangeInternalBotForm,
    ChangeInternalBotSettingsForm,
    ChangeRootOrderForm,
    CreateProjectLabelForm,
    UpdateProjectDetailsForm,
    UpdateProjectLabelDetailsForm,
    UpdateRolesForm,
)


@AppRouter.schema()
@AppRouter.api.get(
    "/board/{project_uid}/details",
    tags=["Board.Settings"],
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
                            "internal_bots": [InternalBot],
                            "internal_bot_settings": {InternalBotType: ProjectAssignedInternalBot},
                            "current_auth_role_actions": [ALL_GRANTED, ProjectRoleAction],
                            "labels": [ProjectLabel],
                            "member_roles": {"<user uid>": [ALL_GRANTED, ProjectRoleAction]},
                            "access_groups": [
                                {
                                    "uid": "string",
                                    "role_key": "string",
                                    "name": "string",
                                    "description": "string",
                                    "member_uids": ["string"],
                                    "member_count": "integer",
                                }
                            ],
                            "chat_templates": [ChatTemplate],
                        }
                    },
                ),
                "internal_bots": [InternalBot],
                "project_columns": [(ProjectColumn, {"schema": {"count": "integer"}})],
                "cards": [(Card, {"schema": {"project_column_name": "string"}})],
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def get_project_details(
    project_uid: str, user_or_bot: User | Bot = Auth.scope("all"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.get_details(user_or_bot, project_uid, is_setting=True)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    project, response = result
    (
        project_internal_bots,
        internal_bot_settings,
    ) = service.project.get_api_assigned_internal_bot_list_with_setting_map(project)
    response["internal_bots"] = project_internal_bots
    response["internal_bot_settings"] = internal_bot_settings

    internal_bots = service.internal_bot.get_api_list(is_setting=False)
    columns = service.project_column.get_api_list_by_project(project)
    cards = service.card.get_api_list_by_project(project)
    templates = service.chat.get_api_template_list(Project.__tablename__, project_uid)

    return JsonResponse(
        content={
            "project": response,
            "internal_bots": internal_bots,
            "columns": columns,
            "cards": cards,
            "chat_templates": templates,
        }
    )


@AppRouter.schema(form=UpdateProjectDetailsForm)
@AppRouter.api.put(
    "/board/{project_uid}/settings/details",
    tags=["Board.Settings"],
    description="Change project details.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def change_project_details(
    project_uid: str,
    form: UpdateProjectDetailsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project.update(user_or_bot, project_uid, form.model_dump())
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse()


@AppRouter.api.put(
    "/board/{project_uid}/settings/internal-bot",
    tags=["Board.Settings"],
    description="Change internal bot for a project.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2019).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def change_project_internal_bot(
    project_uid: str, form: ChangeInternalBotForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.change_internal_bot(project_uid, form.internal_bot_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2019)

    return JsonResponse()


@AppRouter.api.put(
    "/board/{project_uid}/settings/internal-bot/settings",
    tags=["Board.Settings"],
    description="Change internal bot settings for a project.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2019).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def change_project_internal_bot_settings(
    project_uid: str, form: ChangeInternalBotSettingsForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.change_internal_bot_settings(
        project_uid, form.bot_type, form.use_default_prompt, form.prompt
    )
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2019)

    return JsonResponse()


@AppRouter.api.put(
    "/board/{project_uid}/settings/roles/user/{user_uid}",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2006).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def update_project_user_roles(
    project_uid: str, user_uid: str, form: UpdateRolesForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.update_user_roles(project_uid, user_uid, form.roles)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2006)

    return JsonResponse()


@AppRouter.schema(form=CreateProjectLabelForm)
@AppRouter.api.post(
    "/board/{project_uid}/settings/label",
    tags=["Board.Settings"],
    description="Create a project label.",
    responses=(
        OpenApiSchema().suc({"label": ProjectLabel}, 201).auth().forbidden().err(404, ApiErrorCode.NF2001).get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def create_project_label(
    project_uid: str,
    form: CreateProjectLabelForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_label.create(user_or_bot, project_uid, form.name, form.color, form.description)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)
    _, api_label = result

    return JsonResponse(content={"label": api_label}, status_code=status.HTTP_201_CREATED)


@AppRouter.schema(form=UpdateProjectLabelDetailsForm)
@AppRouter.api.put(
    "/board/{project_uid}/settings/label/{label_uid}/details",
    tags=["Board.Settings"],
    description="Change project label details.",
    responses=(
        OpenApiSchema()
        .suc(
            {
                "name?": "string",
                "color?": "string",
                "description?": "string",
            }
        )
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2007)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def change_project_label_details(
    project_uid: str,
    label_uid: str,
    form: UpdateProjectLabelDetailsForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_label.update(user_or_bot, project_uid, label_uid, form.model_dump())
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2007)

    if result is True:
        response = {}
        for key in UpdateProjectLabelDetailsForm.model_fields:
            if ["name", "color", "description"].count(key) == 0:
                continue
            value = getattr(form, key)
            if value is None:
                continue
            response[key] = convert_python_data(value)
        return JsonResponse(content=response)

    return JsonResponse(content=result)


@AppRouter.schema(form=ChangeRootOrderForm)
@AppRouter.api.put(
    "/board/{project_uid}/settings/label/{label_uid}/order",
    tags=["Board.Settings"],
    description="Change project label order.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2007).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def change_project_label_order(
    project_uid: str, label_uid: str, form: ChangeRootOrderForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project_label.change_order(project_uid, label_uid, form.order)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2007)

    return JsonResponse()


@AppRouter.schema()
@AppRouter.api.delete(
    "/board/{project_uid}/settings/label/{label_uid}",
    tags=["Board.Settings"],
    description="Delete a project label.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2007).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def delete_label(
    project_uid: str,
    label_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_label.delete(user_or_bot, project_uid, label_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2007)

    return JsonResponse()


@AppRouter.api.delete(
    "/board/{project_uid}/settings/delete",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().forbidden().err(403, ApiErrorCode.PE2001).err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def delete_project(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if project is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    if project.owner_id != user.id and not user.is_admin:
        raise ApiException.Forbidden_403(ApiErrorCode.PE2001)

    result = service.project.delete(user, project_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse()
