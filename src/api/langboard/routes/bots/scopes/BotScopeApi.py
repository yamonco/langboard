from langboard_shared.ai import BotScopeHelper
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.types.BotRelatedTypes import AVAILABLE_BOT_TARGET_TABLES
from langboard_shared.domain.models import Bot, Project, ProjectRole
from langboard_shared.domain.models.bases import BaseBotScopeModel
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import BotHelper, InfraHelper
from langboard_shared.publishers import ProjectBotPublisher
from langboard_shared.security import RoleFinder
from ..forms import (
    ApplyDefaultBotScopeForm,
    CreateBotScopeForm,
    DeleteBotScopeForm,
    ToggleBotScopeFreezeForm,
    ToggleBotTriggerConditionForm,
)


@AppRouter.schema(form=CreateBotScopeForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/bot/{bot_uid}/scope",
    tags=["Bot.Scope"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA3003).err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def create_bot_scope_in_project(
    bot_uid: str, form: CreateBotScopeForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    """Compatibility adapter for the canonical idempotent Bot Hook service."""

    result = BotHelper.get_target_model_by_param("scope", form.target_table, form.target_uid)
    if not result:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)
    scope_model_class, _ = result
    try:
        hook = service.bot.upsert_hook(
            bot_uid,
            form.target_table,
            form.target_uid,
            form.conditions,
        )
    except ValueError as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003) from error
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    bot_scope = BotScopeHelper.get_by_id_like(scope_model_class, hook["uid"])
    if not bot_scope:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    scope_table = BotHelper.get_target_table_by_bot_model("scope", bot_scope.__class__)
    return JsonResponse(content={"scope_table": scope_table, "bot_scope": bot_scope.api_response()})


@AppRouter.schema(form=ToggleBotTriggerConditionForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bot/{bot_uid}/scope/{bot_scope_uid}/trigger-condition",
    tags=["Bot.Scope"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA3003).err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def toggle_bot_trigger_condition(
    bot_uid: str,
    bot_scope_uid: str,
    form: ToggleBotTriggerConditionForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    scope_model_class = BotHelper.get_bot_model_class("scope", form.target_table)
    if not scope_model_class:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)

    params = InfraHelper.get_records_with_foreign_by_params((Bot, bot_uid), (scope_model_class, bot_scope_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    _, bot_scope = params

    target_scope = _get_target_scope(bot_scope, form.target_table)
    result = BotScopeHelper.toggle_trigger_condition(scope_model_class, bot_scope, form.condition)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    if isinstance(target_scope, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_scope, Project):
            project = target_scope
        else:
            project = service.project.get_by_id_like(target_scope.project_id)

        if project:
            ProjectBotPublisher.scope_conditions_updated(project, bot_scope)

    scope_table = BotHelper.get_target_table_by_bot_model("scope", bot_scope.__class__)
    return JsonResponse(content={"scope_table": scope_table, "bot_scope": bot_scope.api_response()})


@AppRouter.schema(form=ToggleBotScopeFreezeForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bot/{bot_uid}/scope/{bot_scope_uid}/freeze",
    tags=["Bot.Scope"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA3003).err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def toggle_bot_scope_freeze(
    bot_uid: str,
    bot_scope_uid: str,
    form: ToggleBotScopeFreezeForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    scope_model_class = BotHelper.get_bot_model_class("scope", form.target_table)
    if not scope_model_class:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)

    params = InfraHelper.get_records_with_foreign_by_params((Bot, bot_uid), (scope_model_class, bot_scope_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    _, bot_scope = params

    target_scope = _get_target_scope(bot_scope, form.target_table)
    updated_bot_scope = BotScopeHelper.set_freeze(scope_model_class, bot_scope, form.is_frozen)
    if not updated_bot_scope:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    if isinstance(target_scope, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_scope, Project):
            project = target_scope
        else:
            project = service.project.get_by_id_like(target_scope.project_id)

        if project:
            ProjectBotPublisher.scope_freeze_updated(project, updated_bot_scope)

    scope_table = BotHelper.get_target_table_by_bot_model("scope", updated_bot_scope.__class__)
    return JsonResponse(content={"scope_table": scope_table, "bot_scope": updated_bot_scope.api_response()})


@AppRouter.schema(form=DeleteBotScopeForm, permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/bot/{bot_uid}/scope/{bot_scope_uid}",
    tags=["Bot.Scope"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA3003).err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def delete_bot_scope(
    bot_uid: str,
    bot_scope_uid: str,
    form: DeleteBotScopeForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    scope_model_class = BotHelper.get_bot_model_class("scope", form.target_table)
    if not scope_model_class:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)

    params = InfraHelper.get_records_with_foreign_by_params((Bot, bot_uid), (scope_model_class, bot_scope_uid))
    if not params:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    bot, bot_scope = params

    target_scope = _get_target_scope(bot_scope, form.target_table)
    BotScopeHelper.delete(scope_model_class, bot_scope)

    if isinstance(target_scope, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_scope, Project):
            project = target_scope
        else:
            project = service.project.get_by_id_like(target_scope.project_id)

        if project:
            service.graph_approval_request.cancel_pending_by_scope(
                project,
                form.target_table,
                target_scope.get_uid(),
                origin_type=GraphApprovalOriginType.Trigger,
                bot=bot,
                reason="bot scope deleted",
            )
            service.graph_approval_request.cancel_pending_by_scope(
                project,
                form.target_table,
                target_scope.get_uid(),
                origin_type=GraphApprovalOriginType.ManualScopeRun,
                bot=bot,
                reason="bot scope deleted",
            )
            ProjectBotPublisher.scope_deleted(project, bot_scope)

    scope_table = BotHelper.get_target_table_by_bot_model("scope", bot_scope.__class__)
    return JsonResponse(content={"scope_table": scope_table, "bot_scope": bot_scope.api_response()})


@AppRouter.schema(form=ApplyDefaultBotScopeForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bot/{bot_uid}/scope/default",
    tags=["Bot.Scope"],
    responses=OpenApiSchema().auth().forbidden().err(400, ApiErrorCode.VA3003).err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def apply_default_bot_scope(
    bot_uid: str, form: ApplyDefaultBotScopeForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = BotHelper.get_target_model_by_param("scope", form.target_table, form.target_uid)
    if not result:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003)
    scope_model_class, target_scope = result

    bot = service.bot.get_by_id_like(bot_uid)
    if not bot:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    applied = BotScopeHelper.apply_default_scope(scope_model_class, bot, target_scope, form.default_scope_branch_uid)
    if not applied:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    bot_scope, is_created = applied

    if isinstance(target_scope, tuple(AVAILABLE_BOT_TARGET_TABLES.values())):
        if isinstance(target_scope, Project):
            project = target_scope
        else:
            project = service.project.get_by_id_like(target_scope.project_id)

        if project:
            if is_created:
                ProjectBotPublisher.scope_created(project, bot_scope)
            else:
                ProjectBotPublisher.scope_conditions_updated(project, bot_scope)

    return JsonResponse()


def _get_target_scope(bot_scope: BaseBotScopeModel, target_table: str):
    target_id = bot_scope.__dict__.get(bot_scope.get_scope_column_name())
    if not target_id:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)

    result = BotHelper.get_target_model_by_param("scope", target_table, target_id)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    _, target_scope = result
    return target_scope
