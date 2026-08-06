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
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import SettingRole, WebhookSetting
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from .Form import CreateWebhookForm, DeleteSelectedWebhooksForm, UpdateWebhookForm


@AppRouter.api.get(
    "/settings/webhooks",
    tags=["AppSettings.Webhook"],
    responses=OpenApiSchema().suc({"webhooks": [WebhookSetting]}).auth().forbidden().get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_webhooks(service: DomainService = DomainService.scope()) -> JsonResponse:
    settings = service.app_setting.get_api_webhook_setting_list()
    return JsonResponse(content={"webhooks": settings})


@AppRouter.api.get(
    "/settings/webhook/{webhook_uid}",
    tags=["AppSettings.Webhook"],
    responses=OpenApiSchema().suc({"webhook": WebhookSetting}).auth().forbidden().err(404, ApiErrorCode.NF3002).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_webhook(webhook_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    setting = service.app_setting.get_api_webhook_setting(webhook_uid)
    if not setting:
        raise ApiException.NotFound_404(ApiErrorCode.NF3002)
    return JsonResponse(content={"webhook": setting})


@AppRouter.api.post(
    "/settings/webhook",
    tags=["AppSettings.Webhook"],
    responses=(
        OpenApiSchema().suc({"webhook": WebhookSetting, "revealed_value": "string"}, 201).auth().forbidden().get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def create_webhook(form: CreateWebhookForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    setting, revealed_value = service.app_setting.create_webhook_setting(form.name, form.url)

    return JsonResponse(
        content={"webhook": setting.api_response(), "revealed_value": revealed_value},
        status_code=status.HTTP_201_CREATED,
    )


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{webhook_uid}", "webhook"),
        "name",
        "name",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{webhook_uid}", "webhook"),
        "url",
        "url",
    ),
)
@AppRouter.api.put(
    "/settings/webhook/{webhook_uid}",
    tags=["AppSettings.Webhook"],
    responses=OpenApiSchema().suc({"webhook": WebhookSetting}).auth().forbidden().err(404, ApiErrorCode.NF3002).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_webhook(
    webhook_uid: str, form: UpdateWebhookForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.app_setting.update_webhook_setting(webhook_uid, form.name, form.url)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF3002)

    return JsonResponse(content={"webhook": result.api_response()})


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{webhook_uid}", "webhook")
    )
)
@AppRouter.api.delete(
    "/settings/webhook/{webhook_uid}",
    tags=["AppSettings.Webhook"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF3002).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookDelete], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_webhook(webhook_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    result = service.app_setting.delete_webhook_setting(webhook_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF3002)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(EEditorCollaborationType.AppSettings, "{webhook_uids}", "webhook")
    )
)
@AppRouter.api.delete(
    "/settings/webhooks",
    tags=["AppSettings.Webhook"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF3002).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.WebhookDelete], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_selected_webhooks(
    form: DeleteSelectedWebhooksForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.app_setting.delete_selected_webhook_settings(form.webhook_uids)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF3002)

    return JsonResponse()
