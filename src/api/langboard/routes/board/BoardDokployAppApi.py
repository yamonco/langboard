"""Native Dokploy metadata onboarding; credentials use the existing secret store."""

import httpx
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field
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
