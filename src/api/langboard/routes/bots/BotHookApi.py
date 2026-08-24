"""Canonical API for bots subscribing to Langboard events."""

from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from .forms import UpsertBotHookForm


@AppRouter.schema(form=UpsertBotHookForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bots/{bot_uid}/hooks",
    tags=["Bot.Hook"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "hook": {
                    "uid": "string",
                    "bot_uid": "string",
                    "target": {"type": "string", "uid": "string"},
                    "events": ["string"],
                    "active": "boolean",
                }
            }
        )
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA3003)
        .err(404, ApiErrorCode.NF2020)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def upsert_bot_hook(
    bot_uid: str,
    form: UpsertBotHookForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Idempotently subscribe a bot to events on a project, column, or card."""

    try:
        hook = service.bot.upsert_hook(
            bot_uid,
            form.target_table,
            form.target_uid,
            form.events,
            active=form.active,
        )
    except ValueError as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA3003) from error
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    return JsonResponse(content={"hook": hook})
