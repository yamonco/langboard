from fastapi import File, UploadFile, status
from langboard_shared.ai import validate_bot_form
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
from langboard_shared.core.storage import Storage, StorageName
from langboard_shared.domain.models import InternalBot, SettingRole
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from langboard_shared.tasks.docling.DocumentEmbedding import validate_embedding_config
from .Form import CreateInternalBotForm, UpdateInternalBotForm


@AppRouter.api.get(
    "/settings/internal-bots",
    tags=["AppSettings.Bot"],
    responses=OpenApiSchema().suc({"internal_bots": [(InternalBot, {"is_setting": True})]}).auth().forbidden().get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_internal_bots(service: DomainService = DomainService.scope()) -> JsonResponse:
    internal_bots = service.internal_bot.get_api_list(is_setting=True)

    return JsonResponse(content={"internal_bots": internal_bots})


@AppRouter.api.post(
    "/settings/internal-bot",
    tags=["AppSettings.InternalBot"],
    responses=(
        OpenApiSchema()
        .suc({"internal_bot": (InternalBot, {"is_setting": True})}, 201)
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA0000)
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def create_internal_bot(
    form: CreateInternalBotForm = CreateInternalBotForm.scope(),
    avatar: UploadFile | None = File(None),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not validate_bot_form(form):
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)

    if form.bot_type == InternalBotType.DocumentEmbedding:
        if form.platform != BotPlatform.Default or form.platform_running_type != BotPlatformRunningType.Default:
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
        try:
            validate_embedding_config(form.value)
        except (ValueError, TypeError):
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from None

    file_model = Storage.upload(avatar, StorageName.InternalBot) if avatar else None
    internal_bot = service.internal_bot.create(
        form.bot_type,
        form.display_name,
        form.platform,
        form.platform_running_type,
        form.api_url,
        form.value,
        form.api_key,
        file_model,
    )

    return JsonResponse(
        content={"internal_bot": internal_bot.api_response(is_setting=True)},
        status_code=status.HTTP_201_CREATED,
    )


@AppRouter.api.post(
    "/settings/internal-bot/{internal_bot_uid}/copy",
    tags=["AppSettings.InternalBot"],
    responses=(
        OpenApiSchema()
        .suc({"internal_bot": (InternalBot, {"is_setting": True})}, 201)
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF3004)
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def copy_internal_bot(internal_bot_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    internal_bot = service.internal_bot.copy(internal_bot_uid)
    if not internal_bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)

    return JsonResponse(
        content={"internal_bot": internal_bot.api_response(is_setting=True)},
        status_code=status.HTTP_201_CREATED,
    )


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.AppSettings, "{internal_bot_uid}", "internal-bot"
        ),
        "display_name",
        "display_name",
    ),
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.AppSettings, "{internal_bot_uid}", "internal-bot"
        ),
        "api_url",
        "api_url",
    ),
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.AppSettings, "{internal_bot_uid}", "internal-bot-value"
        )
    ),
)
@AppRouter.api.put(
    "/settings/internal-bot/{internal_bot_uid}",
    tags=["AppSettings.InternalBot"],
    responses=(
        OpenApiSchema()
        .suc({"internal_bot": (InternalBot, {"is_setting": True})})
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF3004)
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_internal_bot(
    internal_bot_uid: str,
    form: UpdateInternalBotForm = UpdateInternalBotForm.scope(),
    avatar: UploadFile | None = File(None),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    internal_bot = service.internal_bot.get_by_id_like(internal_bot_uid)
    if not internal_bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)

    form_dict = form.model_dump()
    if internal_bot.bot_type == InternalBotType.DocumentEmbedding:
        platform = form.platform or internal_bot.platform
        running_type = form.platform_running_type or internal_bot.platform_running_type
        if platform != BotPlatform.Default or running_type != BotPlatformRunningType.Default:
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
        try:
            validate_embedding_config(form.value if form.value is not None else internal_bot.value)
        except (ValueError, TypeError):
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from None
    file_model = Storage.upload(avatar, StorageName.InternalBot) if avatar else None
    if file_model:
        form_dict["avatar"] = file_model

    result = service.internal_bot.update(internal_bot, form_dict)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)

    if isinstance(result, bool):
        return JsonResponse()

    return JsonResponse(content={"internal_bot": result.api_response(is_setting=True)})


@AppRouter.api.put(
    "/settings/internal-bot/{internal_bot_uid}/default",
    tags=["AppSettings.InternalBot"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF3004).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def set_internal_bot_default(internal_bot_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    internal_bot = service.internal_bot.change_default(internal_bot_uid)
    if not internal_bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.AppSettings, "{internal_bot_uid}", "internal-bot"
        )
    ),
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.AppSettings, "{internal_bot_uid}", "internal-bot-value"
        )
    ),
)
@AppRouter.api.delete(
    "/settings/internal-bot/{internal_bot_uid}",
    tags=["AppSettings.InternalBot"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF3004).err(409, ApiErrorCode.EX3002).get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotDelete], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_internal_bot(internal_bot_uid: str, service: DomainService = DomainService.scope()) -> JsonResponse:
    internal_bot = service.internal_bot.get_by_id_like(internal_bot_uid)
    if not internal_bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF3004)

    if internal_bot.is_default:
        raise ApiException.Conflict_409(ApiErrorCode.EX3002)

    service.internal_bot.delete(internal_bot)
    return JsonResponse()
