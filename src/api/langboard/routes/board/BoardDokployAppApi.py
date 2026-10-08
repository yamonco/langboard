"""Native Dokploy metadata onboarding; credentials use the existing secret store."""

from typing import Literal
import httpx
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from ...apps import DokployConnection as dokploy


class ConnectionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_url: str = Field(min_length=1, max_length=2048)
    credential_reference: str = Field(pattern=r"^secret://ref/[A-Za-z0-9]{1,11}$")


def _response(command, *args):
    try:
        result = command(*args)
    except dokploy.DokployConflict:
        raise ApiException.Conflict_409() from None
    except (dokploy.DokployUnavailable, SecretReferenceUnavailable):
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
    except httpx.HTTPError:
        raise ApiException.ServiceUnavailable_503() from None
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


@AppRouter.api.post("/board/{project_uid}/settings/apps/dokploy/connections", tags=["Board.Settings"])
@AuthFilter.add("user")
def create_dokploy_connection(
    project_uid: str,
    form: ConnectionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        dokploy.register_connection, service, user, project_uid, form.instance_url, form.credential_reference
    )


@AppRouter.api.get("/board/{project_uid}/settings/apps/dokploy/connections", tags=["Board.Settings"])
@AuthFilter.add("user")
def get_dokploy_connections(
    project_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(dokploy.list_connections, service, user, project_uid, after)


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/resources", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_dokploy_resources(
    project_uid: str,
    connection_uid: str,
    external_project_id: str | None = None,
    environment_id: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        dokploy.discover_resources, service, user, project_uid, connection_uid, external_project_id, environment_id
    )


class RevisionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceForm(RevisionForm):
    resource_type: Literal["project", "environment", "application", "compose"]
    external_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    external_project_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,200}$")
    environment_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,200}$")
    expected_resource_revision: StrictInt | None = Field(default=None, ge=0)


class ResourceRevisionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/selected", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def bind_dokploy_resource(
    project_uid: str,
    connection_uid: str,
    form: ResourceForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        dokploy.bind_resource,
        service,
        user,
        project_uid,
        connection_uid,
        form.resource_type,
        form.external_id,
        form.external_project_id,
        form.environment_id,
        form.expected_revision,
        form.expected_resource_revision,
    )


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/selected", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_dokploy_selected_resources(
    project_uid: str,
    connection_uid: str,
    after: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(dokploy.selected_resources, service, user, project_uid, connection_uid, after)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/selected/{resource_uid}/remove",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def remove_dokploy_resource(
    project_uid: str,
    connection_uid: str,
    resource_uid: str,
    form: ResourceRevisionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        dokploy.remove_resource, service, user, project_uid, connection_uid, resource_uid, form.expected_revision
    )


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/disconnect", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def disconnect_dokploy_connection(
    project_uid: str,
    connection_uid: str,
    form: RevisionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(dokploy.disconnect, service, user, project_uid, connection_uid, form.expected_revision)


@AppRouter.api.post("/board/{project_uid}/settings/apps/dokploy/secret-input", tags=["Board.Settings"])
@AuthFilter.add("user")
def request_dokploy_secret_input(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    from uuid import uuid4
    from ...secrets.SecretInput import begin_input

    def begin():
        dokploy._board(service, user, project_uid)
        return begin_input(service, user, "personal", "me", "dokploy/api-" + uuid4().hex)

    return _response(begin)


@AppRouter.api.get("/board/{project_uid}/settings/apps/dokploy/secret-input/{input_uid}", tags=["Board.Settings"])
@AuthFilter.add("user")
def get_dokploy_secret_input(
    project_uid: str, input_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    from ...secrets.SecretInput import input_status

    def status():
        dokploy._board(service, user, project_uid)
        return input_status(service, user, input_uid)

    return _response(status)


class SignalRefreshForm(RevisionForm):
    expected_access_revision: StrictInt = Field(ge=0)


class ReadAccessForm(RevisionForm):
    expected_binding_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/enable-read",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def enable_dokploy_read_access(
    project_uid: str,
    connection_uid: str,
    form: ReadAccessForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    return _response(
        dokploy.enable_read_access,
        service,
        user,
        project_uid,
        connection_uid,
        form.expected_revision,
        form.expected_binding_revision,
    )


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/selected/{resource_uid}/refresh",
    tags=["Board.Settings"],
)
@AuthFilter.add("user")
def refresh_dokploy_deployments(
    project_uid: str,
    connection_uid: str,
    resource_uid: str,
    form: SignalRefreshForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    from ...apps.DokploySignal import refresh_deployments

    return _response(
        refresh_deployments,
        service,
        user,
        project_uid,
        connection_uid,
        resource_uid,
        form.expected_revision,
        form.expected_access_revision,
    )


class WebhookRevisionForm(ReadAccessForm):
    expected_config_revision: StrictInt = Field(ge=0)


class WebhookConfigForm(WebhookRevisionForm):
    credential_reference: str = Field(pattern=r"^secret://ref/[A-Za-z0-9]{1,11}$")
    notification_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,200}$")


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/webhook-health", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def get_dokploy_webhook_health(
    project_uid: str,
    connection_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    from ...apps.DokployWebhook import health

    return _response(health, service, user, project_uid, connection_uid)


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/webhook-config", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def configure_dokploy_webhook(
    project_uid: str,
    connection_uid: str,
    form: WebhookConfigForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    from ...apps.DokployWebhook import configure

    return _response(
        configure,
        service,
        user,
        project_uid,
        connection_uid,
        form.expected_revision,
        form.expected_binding_revision,
        form.expected_config_revision,
        form.credential_reference,
        form.notification_id,
    )


@AppRouter.api.post(
    "/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}/webhook-disable", tags=["Board.Settings"]
)
@AuthFilter.add("user")
def disable_dokploy_webhook(
    project_uid: str,
    connection_uid: str,
    form: WebhookRevisionForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
):
    from ...apps.DokployWebhook import disable

    return _response(
        disable,
        service,
        user,
        project_uid,
        connection_uid,
        form.expected_revision,
        form.expected_binding_revision,
        form.expected_config_revision,
    )


@AppRouter.api.post("/board/{project_uid}/settings/apps/dokploy/webhook-secret-input", tags=["Board.Settings"])
@AuthFilter.add("user")
def request_dokploy_webhook_secret_input(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
):
    from uuid import uuid4
    from ...secrets.SecretInput import begin_input

    def begin():
        dokploy._board(service, user, project_uid)
        return begin_input(service, user, "personal", "me", "dokploy/webhook-" + uuid4().hex)

    return _response(begin)


from fastapi import Request  # noqa: E402


@AppRouter.api.post("/apps/dokploy/notifications/{config_uid}", tags=["Apps"])
async def receive_dokploy_notification(
    config_uid: str, request: Request, service: DomainService = DomainService.scope()
):
    from ...apps.DokployWebhook import MAX_BODY, authenticate, receive

    def auth():
        try:
            return authenticate(service, config_uid, request.headers.get("Authorization"))
        except (dokploy.DokployUnavailable, dokploy.DokployConflict, SecretReferenceUnavailable, ValueError):
            raise ApiException.NotFound_404() from None

    revision = auth()
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            return JsonResponse(status_code=413, headers={"Cache-Control": "no-store"})
        body.extend(chunk)
    try:
        result = receive(service, config_uid, request.headers.get("Authorization"), bytes(body), revision)
    except (dokploy.DokployUnavailable, dokploy.DokployConflict, SecretReferenceUnavailable):
        raise ApiException.NotFound_404() from None
    except ValueError:
        raise ApiException.BadRequest_400() from None
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})
