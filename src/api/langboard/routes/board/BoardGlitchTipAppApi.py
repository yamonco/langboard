"""Native GlitchTip metadata connections; no raw diagnostics proxy."""

import httpx
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from ...apps import GlitchTipConnection as glitchtip


class ConnectionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_url: str = Field(min_length=1, max_length=2048)
    credential_reference: str = Field(pattern=r"^secret://ref/[A-Za-z0-9]{1,11}$")


class RevisionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProjectForm(RevisionForm):
    organization: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    project_slug: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    expected_resource_revision: StrictInt | None = Field(default=None, ge=0)


class ResourceRevisionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)


def _response(command, *args, **kwargs):
    try:
        result = command(*args, **kwargs)
    except glitchtip.GlitchTipConflict:
        raise ApiException.Conflict_409() from None
    except (glitchtip.GlitchTipUnavailable, SecretReferenceUnavailable):
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
    except httpx.HTTPError:
        raise ApiException.ServiceUnavailable_503() from None
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


@AppRouter.api.post("/board/{project_uid}/settings/apps/glitchtip/connections", tags=["Board.Settings"])
@AuthFilter.add("user")
def create_glitchtip_connection(
    project_uid: str,
    form: ConnectionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        glitchtip.register_connection, service, user, project_uid, form.instance_url, form.credential_reference
    )


@AppRouter.api.get("/board/{project_uid}/settings/apps/glitchtip/connections", tags=["Board.Settings"])
@AuthFilter.add("user")
def get_glitchtip_connections(
    project_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(glitchtip.list_connections, service, user, project_uid, after)


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/resources", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_glitchtip_resources(
    project_uid: str,
    connection_uid: str,
    organization: str | None = None,
    cursor: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(glitchtip.discover_resources, service, user, project_uid, connection_uid, organization, cursor)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/projects", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def bind_glitchtip_project(
    project_uid: str,
    connection_uid: str,
    form: ProjectForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        glitchtip.bind_project,
        service,
        user,
        project_uid,
        connection_uid,
        form.organization,
        form.project_slug,
        form.expected_revision,
        form.expected_resource_revision,
    )


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/projects", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_glitchtip_selected_projects(
    project_uid: str,
    connection_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(glitchtip.selected_projects, service, user, project_uid, connection_uid, after)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/projects/{resource_uid}/remove",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def remove_glitchtip_project(
    project_uid: str,
    connection_uid: str,
    resource_uid: str,
    form: ResourceRevisionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        glitchtip.remove_project, service, user, project_uid, connection_uid, resource_uid, form.expected_revision
    )


@AppRouter.api.post("/board/{project_uid}/settings/apps/glitchtip/secret-input", tags=["Board.Settings"])
@AuthFilter.add("user")
def request_glitchtip_secret_input(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    from uuid import uuid4
    from ...secrets.SecretInput import begin_input

    def begin():
        glitchtip._board(service, user, project_uid)
        return begin_input(service, user, "personal", "me", "glitchtip/api-" + uuid4().hex)

    return _response(begin)


@AppRouter.api.get("/board/{project_uid}/settings/apps/glitchtip/secret-input/{input_uid}", tags=["Board.Settings"])
@AuthFilter.add("user")
def get_glitchtip_secret_input(
    project_uid: str, input_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    from ...secrets.SecretInput import input_status

    def status():
        glitchtip._board(service, user, project_uid)
        return input_status(service, user, input_uid)

    return _response(status)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/disconnect", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def disconnect_glitchtip_connection(
    project_uid: str,
    connection_uid: str,
    form: RevisionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(glitchtip.disconnect, service, user, project_uid, connection_uid, form.expected_revision)


class ReadAccessForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_connection_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_binding_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class IssueRefreshForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_connection_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_access_revision: StrictInt = Field(ge=0)
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{1,256}$")


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/read-access",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def enable_glitchtip_read_access(
    project_uid: str,
    connection_uid: str,
    form: ReadAccessForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        glitchtip.enable_read_access,
        service,
        user,
        project_uid,
        connection_uid,
        form.expected_connection_revision,
        form.expected_binding_revision,
    )


@AppRouter.api.post("/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/disable-read", tags=["Board.Settings"])
@AuthFilter.add("user")
def disable_glitchtip_read_access(
    project_uid: str,
    connection_uid: str,
    form: ReadAccessForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(glitchtip.disable_read_access, service, user, project_uid, connection_uid,
                     form.expected_connection_revision, form.expected_binding_revision)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/glitchtip/connections/{connection_uid}/projects/{resource_uid}/issues/refresh",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def refresh_glitchtip_issues(
    project_uid: str,
    connection_uid: str,
    resource_uid: str,
    form: IssueRefreshForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.GlitchTipSignal import refresh_issues

    return _response(
        refresh_issues,
        service,
        user,
        project_uid,
        connection_uid,
        resource_uid,
        form.expected_connection_revision,
        form.expected_access_revision,
        form.cursor,
    )
