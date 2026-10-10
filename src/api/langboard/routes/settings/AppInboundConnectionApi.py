"""Native inbound service onboarding; no provider credentials or upstream verification."""

from fastapi import Query
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.AppConnectionManagement import (
    create_inbound_connection,
    disconnect_inbound_connection,
    list_inbound_connections,
    list_inbound_resources,
    select_inbound_resource,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.AppRegistry import AppRegistryConflict
from langboard_shared.security import Auth
from pydantic import Field


@form_model
class InboundConnectionForm(BaseFormModel):
    model_config = {"extra": "forbid"}
    app_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    organization_uid: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{11}$")


@form_model
class InboundResourceForm(BaseFormModel):
    model_config = {"extra": "forbid"}
    app_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_uid: str = Field(pattern=r"^[A-Za-z0-9]{11}$")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_type: str = Field(min_length=1, max_length=64)
    external_resource_id: str = Field(min_length=1, max_length=200)
    selected: bool = Field(default=True, strict=True)
    expected_access_revision: int | None = Field(default=None, strict=True, ge=0)


def _run(operation, *args, **kwargs):
    try:
        return JsonResponse(content=operation(*args, **kwargs), headers={"Cache-Control": "no-store"})
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403(ApiErrorCode.PE1001) from exc
    except AppRegistryConflict as exc:
        raise ApiException.Conflict_409(ApiErrorCode.EX3004) from exc
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc


@AppRouter.api.post("/settings/apps/registry/{app_key}/inbound-connections", tags=["AppSettings.Connections"])
@AuthFilter.add("user")
def create_connection(app_key: str, form: InboundConnectionForm, user: User = Auth.scope("user")) -> JsonResponse:
    return _run(
        create_inbound_connection,
        user,
        app_key,
        form.app_revision,
        SnowflakeID.from_short_code(form.organization_uid) if form.organization_uid else None,
    )


@form_model
class DisconnectInboundForm(BaseFormModel):
    model_config = {"extra": "forbid"}
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


@AppRouter.api.get("/settings/apps/registry/{app_key}/inbound-connections", tags=["AppSettings.Connections"])
@AuthFilter.add("user")
def list_connections(
    app_key: str,
    user: User = Auth.scope("user"),
    organization_uid: str | None = Query(default=None, pattern=r"^[A-Za-z0-9]{11}$"),
    after: str | None = Query(default=None, pattern=r"^[A-Za-z0-9]{11}$"),
    limit: int = Query(default=25, ge=1, le=50),
) -> JsonResponse:
    return _run(
        list_inbound_connections,
        user,
        app_key,
        organization_id=SnowflakeID.from_short_code(organization_uid) if organization_uid else None,
        after_id=SnowflakeID.from_short_code(after) if after else None,
        limit=limit,
    )


@AppRouter.api.post("/settings/apps/inbound-connections/{connection_uid}/disconnect", tags=["AppSettings.Connections"])
@AuthFilter.add("user")
def disconnect_connection(
    connection_uid: str, form: DisconnectInboundForm, user: User = Auth.scope("user")
) -> JsonResponse:
    return _run(
        disconnect_inbound_connection, user, SnowflakeID.from_short_code(connection_uid), form.expected_revision
    )


@AppRouter.api.put(
    "/board/{project_uid}/settings/apps/{app_key}/inbound-connections/{connection_uid}/resources", tags=["Board.Apps"]
)
@AuthFilter.add("user")
def select_resource(
    project_uid: str, app_key: str, connection_uid: str, form: InboundResourceForm, user: User = Auth.scope("user")
) -> JsonResponse:
    service = DomainService()
    try:
        return _run(
            select_inbound_resource,
            service.workflow_stage,
            user,
            project_uid,
            app_key,
            form.app_revision,
            form.binding_uid,
            form.expected_revision,
            SnowflakeID.from_short_code(connection_uid),
            form.resource_type,
            form.external_resource_id,
            form.selected,
            form.expected_access_revision,
        )
    finally:
        service.close()


@AppRouter.api.get(
    "/board/{project_uid}/settings/apps/{app_key}/inbound-connections/{connection_uid}/resources", tags=["Board.Apps"]
)
@AuthFilter.add("user")
def list_resources(
    project_uid: str,
    app_key: str,
    connection_uid: str,
    user: User = Auth.scope("user"),
    after: str | None = Query(default=None, pattern=r"^[A-Za-z0-9]{11}$"),
    limit: int = Query(default=25, ge=1, le=50),
) -> JsonResponse:
    service = DomainService()
    try:
        return _run(
            list_inbound_resources,
            service.workflow_stage,
            user,
            project_uid,
            app_key,
            SnowflakeID.from_short_code(connection_uid),
            after_id=SnowflakeID.from_short_code(after) if after else None,
            limit=limit,
        )
    finally:
        service.close()
