from langboard_shared.ai import BotScheduleHelper
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
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.types.BotRelatedTypes import AVAILABLE_BOT_TARGET_TABLES
from langboard_shared.domain.models import Card, Project, ProjectColumn, ProjectRole
from langboard_shared.domain.models.bases import BaseBotScheduleModel
from langboard_shared.domain.models.BotSchedule import BotScheduleRunningType
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import BotHelper
from langboard_shared.publishers import ProjectBotPublisher
from langboard_shared.security import RoleFinder
from ..forms import CreateBotCronTimeForm, DeleteBotCronTimeForm, UpdateBotCronTimeForm


@AppRouter.schema(form=CreateBotCronTimeForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/bot/{bot_uid}/schedule",
    tags=["Bot.Schedule"],
    description="Schedule a bot cron schedule.",
    responses=(
        OpenApiSchema()
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
    form.interval_str = BotScheduleHelper.utils.convert_valid_interval_str(form.interval_str)
    if not form.interval_str:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3001)

    if form.running_type == BotScheduleRunningType.Duration and not form.start_at:
        form.start_at = SafeDateTime.now()

    if not BotScheduleHelper.get_default_status_with_dates(
        running_type=form.running_type, start_at=form.start_at, end_at=form.end_at
    ):
        raise ApiException.BadRequest_400(ApiErrorCode.VA3002)

    result = BotHelper.get_target_model_by_param("schedule", form.target_table, form.target_uid)
    if not result:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3004)
    target_model_class, target_model = result

    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF3001)

    bot_schedule = BotScheduleHelper.schedule(
        target_model_class,
        bot,
        form.interval_str,
        target_model,
        form.running_type,
        form.start_at,
        form.end_at,
        form.timezone,
    )
    if not bot_schedule:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3005)

    if isinstance(target_model, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_model, Project):
            project = target_model
        else:
            project = service.project.get_by_id_like(target_model.project_id)

        if project:
            ProjectBotPublisher.scheduled(project, bot_schedule)

    return JsonResponse()


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
    if form.interval_str:
        form.interval_str = BotScheduleHelper.utils.convert_valid_interval_str(form.interval_str)
        if not form.interval_str:
            raise ApiException.BadRequest_400(ApiErrorCode.VA3001)

    if not BotScheduleHelper.get_default_status_with_dates(
        running_type=form.running_type, start_at=form.start_at, end_at=form.end_at
    ):
        raise ApiException.BadRequest_400(ApiErrorCode.VA3002)

    result = _get_owned_target_model_with_bot_schedule(service, bot_uid, form.target_table, schedule_uid)
    target_model_class, bot_schedule, target_model = result

    result = BotScheduleHelper.reschedule(
        target_model_class,
        bot_schedule,
        form.interval_str,
        form.running_type,
        form.start_at,
        form.end_at,
        form.timezone,
    )
    if not result:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3005)
    _, schedule_model, model = result

    if isinstance(target_model, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_model, Project):
            project = target_model
        else:
            project = service.project.get_by_id_like(target_model.project_id)

        if project:
            ProjectBotPublisher.rescheduled(project, schedule_model, model)

    return JsonResponse()


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
    result = _get_owned_target_model_with_bot_schedule(service, bot_uid, form.target_table, schedule_uid)
    target_model_class, bot_schedule, target_model = result
    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF2015)

    result = BotScheduleHelper.unschedule(target_model_class, bot_schedule)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2015)
    _, schedule_model = result

    if isinstance(target_model, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_model, Project):
            project = target_model
        else:
            project = service.project.get_by_id_like(target_model.project_id)

        if project:
            service.graph_approval_request.cancel_pending_by_scope(
                project,
                form.target_table,
                target_model.get_uid(),
                origin_type=GraphApprovalOriginType.Schedule,
                bot=bot,
                reason="bot schedule deleted",
            )
            ProjectBotPublisher.unscheduled(project, schedule_model)

    return JsonResponse()


def _get_owned_target_model_with_bot_schedule(
    service: DomainService,
    bot_uid: str,
    target_table: str,
    schedule_uid: str,
) -> tuple[type[BaseBotScheduleModel], BaseBotScheduleModel, Project | ProjectColumn | Card]:
    if not BotHelper.get_bot_model_class("schedule", target_table):
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)
    result = service.bot.get_owned_schedule(bot_uid, target_table, schedule_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2015)
    return result
