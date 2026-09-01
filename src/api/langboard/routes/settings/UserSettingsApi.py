from fastapi import status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    collaborative_block,
    collaborative_edit,
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema, PaginatedList
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ApiKeyRole, McpRole, SettingRole, User, UserProfile
from langboard_shared.domain.models.ApiKeyRole import ApiKeyRoleAction
from langboard_shared.domain.models.bases.BaseRoleModel import ALL_GRANTED
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.publishers import AppSettingPublisher
from langboard_shared.security import Auth, RoleFinder
from .Form import (
    CreateUserForm,
    DeleteSelectedUsersForm,
    UpdateApiKeyRoleForm,
    UpdateMcpRoleForm,
    UpdateSettingRoleForm,
    UpdateUserForm,
)


@AppRouter.api.get(
    "/settings/users",
    tags=["AppSettings.User"],
    responses=(
        OpenApiSchema()
        .suc(
            PaginatedList.api_schema(
                (
                    (User, UserProfile),
                    {
                        "schema": {
                            "activated_at": "string?",
                            "is_admin": "bool",
                            "setting_role_actions": [ALL_GRANTED, SettingRoleAction],
                            "api_key_role_actions": [ALL_GRANTED, ApiKeyRoleAction],
                            "mcp_role_actions": [ALL_GRANTED, McpRoleAction],
                        }
                    },
                    {
                        "full_access_emails": [str],
                    },
                )
            )
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_users_in_settings(service: DomainService = DomainService.scope()) -> JsonResponse:
    if service.user.count_not_deleted() > Env.SETTINGS_USER_LIST_MAX_ITEMS:
        raise ApiException.ContentTooLarge_413()

    users = service.user.get_api_list_in_settings()
    full_access_emails = Env.FULL_ADMIN_ACCESS_EMAILS

    return JsonResponse(
        content={
            **PaginatedList(records=users).model_dump(),
            "full_access_emails": list(full_access_emails),
        }
    )


@AppRouter.api.post(
    "/settings/users",
    tags=["AppSettings.User"],
    responses=OpenApiSchema(201).auth().err(409, ApiErrorCode.EX1003).forbidden().get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def create_user_in_settings(form: CreateUserForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    user, _ = service.user.get_by_email(form.email)
    if user:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003)

    form_dict = form.model_dump()
    if form.should_activate:
        now = SafeDateTime.now()
        form_dict["created_at"] = now
        form_dict["updated_at"] = now
        form_dict["activated_at"] = now

    user, user_profile = service.user.create(form_dict)
    api_user = user.api_response()
    api_user.update(user_profile.api_response())
    api_user["created_at"] = user.created_at
    api_user["activated_at"] = user.activated_at
    api_user["is_admin"] = user.is_admin
    api_user["setting_role_actions"] = []
    api_user["api_key_role_actions"] = []
    api_user["mcp_role_actions"] = []
    AppSettingPublisher.user_created({"user": api_user})

    return JsonResponse(status_code=status.HTTP_201_CREATED)


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{user_uid}", "user"),
        "firstname",
        "firstname",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{user_uid}", "user"),
        "lastname",
        "lastname",
    ),
)
@AppRouter.api.put(
    "/settings/users/{user_uid}",
    tags=["AppSettings.User"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF1004).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_user_in_settings(
    user_uid: str, form: UpdateUserForm, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    target_user = service.user.get_by_id_like(user_uid)
    if not target_user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    form_dict = form.model_dump(exclude_unset=True)
    if user.id != target_user.id:
        if form.activate:
            form_dict["activated_at"] = SafeDateTime.now()
        elif form.activate is False:
            form_dict["activated_at"] = None

    service.user.update(target_user, form_dict, from_setting=True)

    if form.password:
        service.user.change_password(target_user, form.password)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{user_uid}", "user")
    )
)
@AppRouter.api.delete(
    "/settings/users/{user_uid}",
    tags=["AppSettings.User"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF1004).err(409, ApiErrorCode.OP1003).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserDelete], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_user_in_settings(
    user_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    target_user = service.user.get_by_id_like(user_uid)
    if not target_user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    if target_user.id == user.id:
        raise ApiException.Conflict_409(ApiErrorCode.OP1003)

    service.user.delete(target_user)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{user_uids}", "user")
    )
)
@AppRouter.api.delete("/settings/users", tags=["AppSettings.User"], responses=OpenApiSchema().auth().forbidden().get())
@RoleFilter.add(SettingRole, [SettingRoleAction.UserDelete], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_selected_users_in_settings(
    form: DeleteSelectedUsersForm, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    user_uid = user.get_uid()
    form.user_uids = [uid for uid in form.user_uids if uid != user_uid]

    service.user.delete_selected(form.user_uids)

    return JsonResponse()


@AppRouter.api.put(
    "/settings/users/{user_uid}/setting-role",
    tags=["AppSettings.User"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF1004).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_user_setting_role(
    user_uid: str,
    form: UpdateSettingRoleForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    target_user = service.user.get_by_id_like(user_uid)
    if not target_user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    # Prevent self-demotion from super admin
    if user.id == target_user.id:
        all_actions = list(SettingRoleAction._member_map_.values())
        if set(form.actions) != set(all_actions):
            raise ApiException.BadRequest_400(ApiErrorCode.OP1003)

    # Grant all permissions
    all_actions = list(SettingRoleAction._member_map_.values())
    if set(form.actions) == set(all_actions) or ALL_GRANTED in form.actions:
        service.user.grant_all_setting_roles(target_user)
    elif not form.actions:
        service.user.grant_setting_roles(target_user, [])
    else:
        service.user.grant_setting_roles(target_user, form.actions)

    return JsonResponse()


@AppRouter.api.put(
    "/settings/users/{user_uid}/api-key-role",
    tags=["AppSettings.User"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF1004).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_user_api_key_role(
    user_uid: str, form: UpdateApiKeyRoleForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    target_user = service.user.get_by_id_like(user_uid)
    if not target_user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    all_actions = ApiKeyRole.get_all_actions()

    if set(form.actions) == set(all_actions) or ALL_GRANTED in form.actions:
        service.api_key.grant_all_roles(target_user)
    elif not form.actions:
        service.api_key.grant_roles(target_user, [])
    else:
        service.api_key.grant_roles(target_user, form.actions)

    return JsonResponse()


@AppRouter.api.put(
    "/settings/users/{user_uid}/mcp-role",
    tags=["AppSettings.User"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF1004).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.UserUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_user_mcp_role(
    user_uid: str, form: UpdateMcpRoleForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    target_user = service.user.get_by_id_like(user_uid)
    if not target_user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    all_actions = McpRole.get_all_actions()

    if set(form.actions) == set(all_actions) or ALL_GRANTED in form.actions:
        service.mcp_tool_group.grant_all_roles(target_user)
    elif not form.actions:
        service.mcp_tool_group.grant_roles(target_user, [])
    else:
        service.mcp_tool_group.grant_roles(target_user, form.actions)

    return JsonResponse()
