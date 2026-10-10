"""Canonical project-scoped API for Bot event Hooks."""

from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.BotService import BotServiceError
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import UpdateBotHookForm, UpsertBotHookForm


BOT_HOOK_SCHEMA = {
    "hook": {
        "uid": "string",
        "bot_uid": "string",
        "target": {"type": "string", "uid": "string"},
        "events": ["string"],
        "active": "boolean",
    }
}
BOT_HOOK_RECEIPT_SCHEMA = {"receipt": {"operation": "string", **BOT_HOOK_SCHEMA}}


@AppRouter.schema(form=UpsertBotHookForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/bots/{bot_uid}/hooks",
    tags=["Bot.Hook"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                **BOT_HOOK_SCHEMA,
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
    actor: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Compatibility route; project-scoped clients should use the canonical route."""

    _ensure_bot_author(actor, bot_uid, service=service)
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


@AppRouter.schema(form=UpsertBotHookForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/projects/{project_uid}/bots/{bot_uid}/hooks",
    tags=["Bot.Hook"],
    responses=(
        OpenApiSchema()
        .suc(BOT_HOOK_RECEIPT_SCHEMA)
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA3003)
        .err(404, ApiErrorCode.NF2020)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def upsert_project_bot_hook(
    project_uid: str,
    bot_uid: str,
    form: UpsertBotHookForm,
    actor: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Idempotently converge one Bot Hook inside an authorized project."""

    _ensure_bot_author(actor, bot_uid, project_uid=project_uid, service=service)
    try:
        hook = service.bot.upsert_hook(
            bot_uid,
            form.target_table,
            form.target_uid,
            form.events,
            active=form.active,
            project=project_uid,
        )
    except ValueError as error:
        _raise_hook_api_error(error)
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    return JsonResponse(content={"receipt": {"operation": "upserted", "hook": hook}})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/projects/{project_uid}/bots/{bot_uid}/hooks/{target_table}/{hook_uid}",
    tags=["Bot.Hook"],
    responses=OpenApiSchema().suc(BOT_HOOK_SCHEMA).auth().forbidden().err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_project_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    actor: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Read one Bot-owned Hook inside an authorized project."""

    _ensure_bot_author(actor, bot_uid, project_uid=project_uid, service=service)
    try:
        hook = service.bot.get_hook(bot_uid, target_table, hook_uid, project=project_uid)
    except ValueError as error:
        _raise_hook_api_error(error)
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    return JsonResponse(content={"hook": hook})


@AppRouter.schema(form=UpdateBotHookForm, permission=ApiPermission.Edit)
@AppRouter.api.patch(
    "/projects/{project_uid}/bots/{bot_uid}/hooks/{target_table}/{hook_uid}",
    tags=["Bot.Hook"],
    responses=(
        OpenApiSchema()
        .suc(BOT_HOOK_RECEIPT_SCHEMA)
        .auth()
        .forbidden()
        .err(400, ApiErrorCode.VA3003)
        .err(404, ApiErrorCode.NF2020)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def update_project_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    form: UpdateBotHookForm,
    actor: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Update one Bot-owned Hook inside an authorized project."""

    _ensure_bot_author(actor, bot_uid, project_uid=project_uid, service=service)
    try:
        hook = service.bot.update_hook(
            bot_uid,
            target_table,
            hook_uid,
            events=form.events,
            active=form.active,
            project=project_uid,
        )
    except ValueError as error:
        _raise_hook_api_error(error)
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    return JsonResponse(content={"receipt": {"operation": "updated", "hook": hook}})


@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/projects/{project_uid}/bots/{bot_uid}/hooks/{target_table}/{hook_uid}",
    tags=["Bot.Hook"],
    responses=OpenApiSchema().suc(BOT_HOOK_RECEIPT_SCHEMA).auth().forbidden().err(404, ApiErrorCode.NF2020).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def delete_project_bot_hook(
    project_uid: str,
    bot_uid: str,
    target_table: str,
    hook_uid: str,
    actor: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Delete one Bot-owned Hook inside an authorized project."""

    _ensure_bot_author(actor, bot_uid, project_uid=project_uid, service=service)
    try:
        hook = service.bot.delete_hook(bot_uid, target_table, hook_uid, project=project_uid)
    except ValueError as error:
        _raise_hook_api_error(error)
    if not hook:
        raise ApiException.NotFound_404(ApiErrorCode.NF2020)
    return JsonResponse(content={"receipt": {"operation": "deleted", "hook": hook}})


def _ensure_bot_author(
    actor: User | Bot,
    bot_uid: str,
    *,
    project_uid: str | None = None,
    service: DomainService,
) -> None:
    """Prevent one authenticated Bot from authoring changes as another Bot."""

    if isinstance(actor, Bot):
        if actor.get_uid() != bot_uid or not project_uid or not service.bot.has_project_access(actor, project_uid):
            raise ApiException.Forbidden_403(ApiErrorCode.PE1001)


def _raise_hook_api_error(error: ValueError) -> None:
    """Translate the shared Hook boundary without leaking cross-project existence."""

    if isinstance(error, BotServiceError) and error.code == "project_mismatch":
        raise ApiException.NotFound_404(ApiErrorCode.NF2020) from error
    raise ApiException.BadRequest_400(ApiErrorCode.VA3003) from error
