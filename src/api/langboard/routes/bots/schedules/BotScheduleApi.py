from typing import NoReturn
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
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.BotService import BotServiceError
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from ..forms import CreateBotCronTimeForm, DeleteBotCronTimeForm, UpdateBotCronTimeForm


BOT_SCHEDULE_RECEIPT_SCHEMA = {
    "receipt": {
        "operation": "string",
        "schedule": {
            "uid": "string",
            "bot_uid": "string",
            "target": {"type": "string", "uid": "string"},
        },
        "changes": "object",
    }
}


@AppRouter.schema(form=CreateBotCronTimeForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/bot/{bot_uid}/schedule",
    tags=["Bot.Schedule"],
    description="Schedule a bot cron schedule.",
    responses=(
        OpenApiSchema()
        .suc(BOT_SCHEDULE_RECEIPT_SCHEMA)
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA3001, ApiErrorCode.VA3002, ApiErrorCode.VA3004, ApiErrorCode.VA3005)
        .err(404, ApiErrorCode.NF3001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def schedule_bot_crons(
    bot_uid: str, form: CreateBotCronTimeForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    try:
        receipt = service.bot.create_schedule(
            bot_uid,
            form.target_table,
            form.target_uid,
            form.interval_str,
            form.running_type,
            form.start_at,
            form.end_at,
            form.timezone,
        )
    except BotServiceError as error:
        _raise_schedule_api_error(error, creating=True)
    return JsonResponse(content={"receipt": receipt})


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BotSchedule, "{project_uid}", "{target_table}-{target_uid}-{schedule_uid}"
        )
    )
)
@AppRouter.schema(form=UpdateBotCronTimeForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bot/{bot_uid}/reschedule/{schedule_uid}",
    tags=["Bot.Schedule"],
    description="Reschedule a bot cron schedule.",
    responses=(
        OpenApiSchema()
        .suc(BOT_SCHEDULE_RECEIPT_SCHEMA)
        .auth()
        .forbidden()
        .err(
            400, ApiErrorCode.VA3001, ApiErrorCode.VA3002, ApiErrorCode.VA3003, ApiErrorCode.VA3004, ApiErrorCode.VA3005
        )
        .err(404, ApiErrorCode.NF2015)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def reschedule_bot_crons(
    bot_uid: str, schedule_uid: str, form: UpdateBotCronTimeForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    try:
        receipt = service.bot.update_schedule(
            bot_uid,
            form.target_table,
            schedule_uid,
            form.interval_str,
            form.running_type,
            form.start_at,
            form.end_at,
            form.timezone,
        )
    except BotServiceError as error:
        _raise_schedule_api_error(error)
    return JsonResponse(content={"receipt": receipt})


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BotSchedule, "{project_uid}", "{target_table}-{target_uid}-{schedule_uid}"
        )
    )
)
@AppRouter.schema(form=DeleteBotCronTimeForm, permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/bot/{bot_uid}/unschedule/{schedule_uid}",
    tags=["Bot.Schedule"],
    description="Unschedule a bot cron schedule.",
    responses=(
        OpenApiSchema()
        .suc(BOT_SCHEDULE_RECEIPT_SCHEMA)
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA3003, ApiErrorCode.VA3004)
        .err(404, ApiErrorCode.NF2015)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def unschedule_bot_crons(
    bot_uid: str, schedule_uid: str, form: DeleteBotCronTimeForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    try:
        receipt = service.bot.delete_schedule(bot_uid, form.target_table, schedule_uid)
    except BotServiceError as error:
        _raise_schedule_api_error(error)
    return JsonResponse(content={"receipt": receipt})


def _raise_schedule_api_error(error: BotServiceError, *, creating: bool = False) -> NoReturn:
    """Translate the shared Bot Schedule error contract to legacy REST codes."""

    if error.code == "invalid_interval":
        raise ApiException.BadRequest_400(ApiErrorCode.VA3001) from error
    if error.code == "invalid_window":
        raise ApiException.BadRequest_400(ApiErrorCode.VA3002) from error
    if error.code == "target_type_invalid":
        code = ApiErrorCode.VA3004 if creating else ApiErrorCode.VA3003
        raise ApiException.BadRequest_400(code) from error
    if error.code == "target_not_found":
        raise ApiException.BadRequest_400(ApiErrorCode.VA3004) from error
    if error.code in {"bot_not_found", "schedule_not_found"}:
        code = ApiErrorCode.NF3001 if creating else ApiErrorCode.NF2015
        raise ApiException.NotFound_404(code) from error
    raise ApiException.BadRequest_400(ApiErrorCode.VA3005) from error
