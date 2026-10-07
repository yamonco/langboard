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
            )
        )
    except GitHubManifestUnavailable:
        raise ApiException.NotFound_404() from None
    except GitHubResourceConflict:
        raise ApiException.Conflict_409() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
