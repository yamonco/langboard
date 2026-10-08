"""Native authenticated GitHub App registration, separate from installation."""

from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from ...apps.GitHubManifest import COOKIE, TTL, GitHubManifestUnavailable, begin_manifest, complete_manifest


class GitHubManifestForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=40, max_length=64)
    code: str = Field(min_length=20, max_length=128)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/github/manifest",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().get(),
)
@AuthFilter.add("user")
def start_github_manifest(
    project_uid: str,
    organization: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    try:
        payload, session = begin_manifest(service, user, project_uid, organization)
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
    response = JsonResponse(content=payload)
    response.set_cookie(
        COOKIE,
        session,
        max_age=TTL,
        httponly=True,
        secure=Env.ENVIRONMENT != "development",
        samesite="lax",
        path=f"/board/{project_uid}/settings/apps/github",
    )
    return response


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/github/manifest/complete",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().get(),
)
@AuthFilter.add("user")
def finish_github_manifest(
    project_uid: str,
    request: Request,
    form: GitHubManifestForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    try:
        payload = complete_manifest(service, user, project_uid, form.state, form.code, request.cookies.get(COOKIE))
    except GitHubManifestUnavailable:
        raise ApiException.BadRequest_400() from None
    response = JsonResponse(content=payload)
    response.delete_cookie(COOKIE, path=f"/board/{project_uid}/settings/apps/github")
    return response


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/installations/{installation_id}/repositories",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().get(),
)
@AuthFilter.add("user")
def get_github_installation_repositories(
    project_uid: str,
    installation_id: int,
    connection_uid: str,
    account_id: int,
    page: int = 1,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubInstallation import inspect_installation

    try:
        result = inspect_installation(service, user, project_uid, connection_uid, installation_id, account_id, page)
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    return JsonResponse(content=result)


class GitHubResourceDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_uid: str = Field(min_length=1, max_length=11)
    installation_id: int = Field(strict=True, gt=0)
    account_id: int = Field(strict=True, gt=0)
    add: list[StrictInt] = Field(default_factory=list, max_length=25)
    remove: list[StrictInt] = Field(default_factory=list, max_length=25)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    installation_proof: str | None = Field(default=None, min_length=40, max_length=64)


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/resources",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().get(),
)
@AuthFilter.add("user")
def get_github_resources(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    from ...apps.GitHubResources import get_resources

    try:
        return JsonResponse(content=get_resources(service, user, project_uid))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None


@AppRouter.api.put(
    "/board/{project_uid}/settings/apps/github/resources",
    tags=["Board.Settings"],
    responses=OpenApiSchema().auth().get(),
)
@AuthFilter.add("user")
def save_github_resources(
    project_uid: str,
    form: GitHubResourceDelta,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubResources import GitHubResourceConflict, update_resources

    try:
        return JsonResponse(
            content=update_resources(
                service,
                user,
                project_uid,
                form.connection_uid,
                form.installation_id,
                form.account_id,
                tuple(form.add),
                tuple(form.remove),
                form.expected_revision,
                form.installation_proof,
            )
        )
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except GitHubResourceConflict:
        raise ApiException.Conflict_409() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None


class GitHubAuthorizationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, strict=True, ge=1, le=10000)
    connection_uid: str = Field(min_length=1, max_length=11)


@AppRouter.api.post("/board/{project_uid}/settings/apps/github/authorization", tags=["Board.Settings"])
@AuthFilter.add("user")
def start_github_authorization(
    project_uid: str,
    form: GitHubAuthorizationStart,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubAuthorization import COOKIE as AUTH_COOKIE
    from ...apps.GitHubAuthorization import begin_authorization

    try:
        payload, session = begin_authorization(service, user, project_uid, form.connection_uid, form.page)
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    response = JsonResponse(content=payload)
    response.set_cookie(
        AUTH_COOKIE,
        session,
        max_age=TTL,
        httponly=True,
        secure=Env.ENVIRONMENT != "development",
        samesite="lax",
        path=f"/board/{project_uid}/settings/apps/github",
    )
    return response


class GitHubAuthorizationComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=40, max_length=64)
    code: str = Field(min_length=20, max_length=128)


@AppRouter.api.post("/board/{project_uid}/settings/apps/github/authorization/complete", tags=["Board.Settings"])
@AuthFilter.add("user")
def finish_github_authorization(
    project_uid: str,
    request: Request,
    form: GitHubAuthorizationComplete,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubAuthorization import COOKIE as AUTH_COOKIE
    from ...apps.GitHubAuthorization import complete_authorization

    try:
        result = complete_authorization(
            service, user, project_uid, form.state, form.code, request.cookies.get(AUTH_COOKIE)
        )
    except GitHubManifestUnavailable:
        raise ApiException.BadRequest_400() from None
    response = JsonResponse(content=result)
    response.delete_cookie(AUTH_COOKIE, path=f"/board/{project_uid}/settings/apps/github")
    return response


@AppRouter.api.get("/board/{project_uid}/settings/apps/github/connections", tags=["Board.Settings"])
@AuthFilter.add("user")
def get_github_connections(
    project_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubConnections import list_connections

    if after is not None and (not after or len(after) > 11):
        raise ApiException.BadRequest_400()
    try:
        return JsonResponse(content=list_connections(service, user, project_uid, after))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/connections/{connection_uid}/app", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_github_app(
    project_uid: str,
    connection_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubConnections import inspect_app

    if not connection_uid or len(connection_uid) > 11:
        raise ApiException.BadRequest_400()
    try:
        return JsonResponse(content=inspect_app(service, user, project_uid, connection_uid))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None


class GitHubResourceRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: str | None = Field(default=None, min_length=1, max_length=11)
    connection_uid: str = Field(min_length=1, max_length=11)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


@AppRouter.api.post("/board/{project_uid}/settings/apps/github/resources/refresh", tags=["Board.Settings"])
@AuthFilter.add("user")
def refresh_github_resources(
    project_uid: str,
    form: GitHubResourceRefresh,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubResources import GitHubResourceConflict, refresh_resources

    try:
        return JsonResponse(
            content=refresh_resources(
                service, user, project_uid, form.connection_uid, form.expected_revision, form.after
            )
        )
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except GitHubResourceConflict:
        raise ApiException.Conflict_409() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None


async def github_webhook_body(request: Request) -> bytes | JsonResponse:
    from ...apps.GitHubLifecycle import MAX_BODY

    # GitHub authenticates original bytes with its webhook HMAC, not browser cookies.
    for name in (
        "content-type",
        "content-length",
        "content-encoding",
        "x-hub-signature-256",
        "x-github-event",
        "x-github-delivery",
        "x-github-hook-installation-target-id",
    ):
        if len(request.headers.getlist(name)) > 1:
            return JsonResponse(status_code=400)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return JsonResponse(status_code=415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        return JsonResponse(status_code=415)
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdigit():
            return JsonResponse(status_code=400)
        if len(length) > 10 or int(length) > MAX_BODY:
            return JsonResponse(status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            return JsonResponse(status_code=413)
        body.extend(chunk)
    if length is not None and int(length) != len(body):
        return JsonResponse(status_code=400)
    return bytes(body)


@AppRouter.api.post("/apps/github/events", tags=["Apps.GitHub"])
async def receive_github_lifecycle(request: Request, service: DomainService = DomainService.scope()) -> JsonResponse:
    from starlette.concurrency import run_in_threadpool
    from ...apps.GitHubLifecycle import (
        GitHubDeliveryConflict,
        receive_external_lifecycle,
    )

    body = await github_webhook_body(request)
    if isinstance(body, JsonResponse):
        return body
    signature = request.headers.get("x-hub-signature-256", "")
    event = request.headers.get("x-github-event", "")
    delivery = request.headers.get("x-github-delivery", "")
    try:
        await run_in_threadpool(
            receive_external_lifecycle,
            service,
            bytes(body),
            signature,
            event,
            delivery,
            request.headers.get("x-github-hook-installation-target-id"),
        )
    except GitHubDeliveryConflict:
        return JsonResponse(status_code=409)
    except GitHubManifestUnavailable:
        return JsonResponse(status_code=400)
    # Receipt and health job are durable; asynchronous completion is separate.
    return JsonResponse(status_code=202)


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/connections/{connection_uid}/health", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_github_connection_health(
    project_uid: str,
    connection_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubConnections import connection_health

    try:
        return JsonResponse(content=connection_health(service, user, project_uid, connection_uid, after))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/connections/{connection_uid}/jobs", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_github_health_jobs(
    project_uid: str,
    connection_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubConnections import health_jobs

    try:
        return JsonResponse(content=health_jobs(service, user, project_uid, connection_uid, after))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None


@AppRouter.api.post(
    "/apps/github/boards/{project_uid}/connections/{connection_uid}/resources/{resource_uid}/events",
    tags=["Apps.GitHub"],
)
async def receive_github_check(
    project_uid: str, connection_uid: str, resource_uid: str, request: Request,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from starlette.concurrency import run_in_threadpool
    from ...apps.GitHubLifecycle import GitHubDeliveryConflict
    from ...apps.GitHubSignal import receive_check

    body = await github_webhook_body(request)
    if isinstance(body, JsonResponse):
        return body
    try:
        await run_in_threadpool(
            receive_check, service, project_uid, connection_uid, resource_uid, body,
            request.headers.get("x-hub-signature-256", ""),
            request.headers.get("x-github-event", ""), request.headers.get("x-github-delivery", ""),
        )
    except GitHubDeliveryConflict:
        return JsonResponse(status_code=409)
    except (GitHubManifestUnavailable, ValueError):
        return JsonResponse(status_code=400)
    return JsonResponse(status_code=202)


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/github/connections/{connection_uid}/resources/{resource_uid}/signals",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def get_github_signals(
    project_uid: str, connection_uid: str, resource_uid: str, after: str | None = None,
    user: User = Auth.scope("user"), service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GitHubSignal import list_signals

    try:
        return JsonResponse(content=list_signals(service, user, project_uid, connection_uid, resource_uid, after))
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
