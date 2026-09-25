from typing import Any
from fastapi import Depends, Request, Response, status
from langboard_shared.core.exceptions import ScimProvisioningException
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from .Form import ScimGroupUpsertForm, ScimListPagination, ScimPatchForm, ScimUserUpsertForm


def _scim_user_example() -> dict[str, Any]:
    return {
        "schemas": ["string"],
        "id": "string",
        "externalId": "string",
        "userName": "string",
        "name": {
            "givenName": "string",
            "familyName": "string",
        },
        "displayName": "string",
        "active": "bool",
        "emails": [{"value": "string", "primary": "bool"}],
        "meta": {
            "resourceType": "string",
            "created": "string",
            "lastModified": "string",
        },
    }


def _scim_group_example() -> dict[str, Any]:
    return {
        "schemas": ["string"],
        "id": "string",
        "externalId": "string",
        "displayName": "string",
        "members": [{"value": "string", "display": "string", "$ref": "string"}],
        "meta": {
            "resourceType": "string",
            "created": "string",
            "lastModified": "string",
        },
    }


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/scim/v2/ServiceProviderConfig",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "schemas": ["string"],
                "patch": {"supported": "bool"},
                "bulk": {"supported": "bool"},
                "filter": {"supported": "bool", "maxResults": "integer"},
                "changePassword": {"supported": "bool"},
                "sort": {"supported": "bool"},
                "etag": {"supported": "bool"},
            }
        )
        .err(401, ApiErrorCode.AU1001)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def scim_service_provider_config(request: Request) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    return JsonResponse(
        content={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True},
            "bulk": {"supported": False},
            "filter": {"supported": True, "maxResults": 200},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "Bearer Token",
                    "description": "Authentication scheme using the Authorization Bearer header.",
                    "primary": True,
                }
            ],
        }
    )


@AppRouter.schema(query=ScimListPagination, permission=ApiPermission.Read)
@AppRouter.api.get(
    "/scim/v2/Users",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "schemas": ["string"],
                "totalResults": "integer",
                "startIndex": "integer",
                "itemsPerPage": "integer",
                "Resources": [_scim_user_example()],
            }
        )
        .err(401, ApiErrorCode.AU1001)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def list_scim_users(
    request: Request,
    pagination: ScimListPagination = Depends(),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    try:
        result = service.scim_provisioning.list_users(
            start_index=pagination.start_index,
            count=pagination.count,
            filter_value=pagination.filter,
        )
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return JsonResponse(content=result)


@AppRouter.schema(query=ScimListPagination, permission=ApiPermission.Read)
@AppRouter.api.get(
    "/scim/v2/Groups",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "schemas": ["string"],
                "totalResults": "integer",
                "startIndex": "integer",
                "itemsPerPage": "integer",
                "Resources": [_scim_group_example()],
            }
        )
        .err(401, ApiErrorCode.AU1001)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def list_scim_groups(
    request: Request,
    pagination: ScimListPagination = Depends(),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    try:
        result = service.scim_provisioning.list_groups(
            start_index=pagination.start_index,
            count=pagination.count,
            filter_value=pagination.filter,
        )
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return JsonResponse(content=result)


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/scim/v2/Groups/{group_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_group_example())
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def get_scim_group(group_id: str, request: Request, service: DomainService = DomainService.scope()) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    group = service.scim_provisioning.resolve_group(group_id)
    if not group:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    return JsonResponse(content=service.scim_provisioning.build_scim_group(group))


@AppRouter.schema(form=ScimGroupUpsertForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/scim/v2/Groups",
    tags=["SCIM"],
    responses=(
        OpenApiSchema(201)
        .suc(_scim_group_example(), status_code=201)
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(409, ApiErrorCode.EX1003)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def create_scim_group(
    form: ScimGroupUpsertForm, request: Request, service: DomainService = DomainService.scope()
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    payload = form.model_dump(exclude_unset=True, by_alias=True)
    try:
        group = service.scim_provisioning.create_or_upsert_group(payload)
    except ScimProvisioningException.InvalidRequest as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error

    return JsonResponse(status_code=status.HTTP_201_CREATED, content=service.scim_provisioning.build_scim_group(group))


@AppRouter.schema(form=ScimGroupUpsertForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/scim/v2/Groups/{group_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_group_example())
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(409, ApiErrorCode.EX1003)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def replace_scim_group(
    group_id: str,
    form: ScimGroupUpsertForm,
    request: Request,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    group = service.scim_provisioning.resolve_group(group_id)
    if not group:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    payload = form.model_dump(exclude_unset=True, by_alias=True)
    try:
        service.scim_provisioning.apply_group_mutations(group, payload)
    except ScimProvisioningException.InvalidRequest as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return JsonResponse(content=service.scim_provisioning.build_scim_group(group))


@AppRouter.schema(form=ScimPatchForm, permission=ApiPermission.Edit)
@AppRouter.api.patch(
    "/scim/v2/Groups/{group_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_group_example())
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(409, ApiErrorCode.EX1003)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def patch_scim_group(
    group_id: str,
    form: ScimPatchForm,
    request: Request,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    group = service.scim_provisioning.resolve_group(group_id)
    if not group:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    operations = [op.model_dump(exclude_unset=True, by_alias=True) for op in form.Operations]
    try:
        service.scim_provisioning.apply_group_patch(group, operations)
    except ScimProvisioningException.InvalidRequest as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error

    return JsonResponse(content=service.scim_provisioning.build_scim_group(group))


@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/scim/v2/Groups/{group_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema(204)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def delete_scim_group(group_id: str, request: Request, service: DomainService = DomainService.scope()) -> Response:
    Auth.ensure_scim_authorized(request.headers)
    group = service.scim_provisioning.resolve_group(group_id)
    if not group:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    try:
        service.scim_provisioning.delete_group(group)
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/scim/v2/Users/{user_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_user_example())
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def get_scim_user(user_id: str, request: Request, service: DomainService = DomainService.scope()) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    user = service.scim_provisioning.resolve_user(user_id)
    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    return JsonResponse(content=service.scim_provisioning.build_scim_user(user))


@AppRouter.schema(form=ScimUserUpsertForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/scim/v2/Users",
    tags=["SCIM"],
    responses=(
        OpenApiSchema(201)
        .suc(_scim_user_example(), status_code=201)
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(409, ApiErrorCode.EX1003, ApiErrorCode.EX1005, ApiErrorCode.EX1006)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def create_scim_user(
    form: ScimUserUpsertForm, request: Request, service: DomainService = DomainService.scope()
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    payload = form.model_dump(exclude_unset=True)
    try:
        user = service.scim_provisioning.create_or_upsert_user(payload)
    except ScimProvisioningException.InvalidRequest as error:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from error
    except ScimProvisioningException.IdentityLinkRequired as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1005) from error
    except ScimProvisioningException.ExternalIdentityConflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1006) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error

    return JsonResponse(status_code=status.HTTP_201_CREATED, content=service.scim_provisioning.build_scim_user(user))


@AppRouter.schema(form=ScimUserUpsertForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/scim/v2/Users/{user_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_user_example())
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(409, ApiErrorCode.EX1003, ApiErrorCode.EX1005, ApiErrorCode.EX1006)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def replace_scim_user(
    user_id: str,
    form: ScimUserUpsertForm,
    request: Request,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    user = service.scim_provisioning.resolve_user(user_id)
    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    payload = form.model_dump(exclude_unset=True)
    try:
        service.scim_provisioning.apply_user_mutations(user, payload)
    except ScimProvisioningException.IdentityLinkRequired as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1005) from error
    except ScimProvisioningException.ExternalIdentityConflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1006) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return JsonResponse(content=service.scim_provisioning.build_scim_user(user))


@AppRouter.schema(form=ScimPatchForm, permission=ApiPermission.Edit)
@AppRouter.api.patch(
    "/scim/v2/Users/{user_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema()
        .suc(_scim_user_example())
        .err(400, ApiErrorCode.VA0000)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(409, ApiErrorCode.EX1003, ApiErrorCode.EX1005, ApiErrorCode.EX1006)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def patch_scim_user(
    user_id: str,
    form: ScimPatchForm,
    request: Request,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    Auth.ensure_scim_authorized(request.headers)
    user = service.scim_provisioning.resolve_user(user_id)
    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    operations = [op.model_dump(exclude_unset=True) for op in form.Operations]
    normalized_payload = service.scim_provisioning.normalize_patch_payload(operations)
    try:
        service.scim_provisioning.apply_user_mutations(user, normalized_payload)
    except ScimProvisioningException.IdentityLinkRequired as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1005) from error
    except ScimProvisioningException.ExternalIdentityConflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1006) from error
    except ScimProvisioningException.Conflict as error:
        raise ApiException.Conflict_409(ApiErrorCode.EX1003) from error
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error

    return JsonResponse(content=service.scim_provisioning.build_scim_user(user))


@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/scim/v2/Users/{user_id}",
    tags=["SCIM"],
    responses=(
        OpenApiSchema(204)
        .err(401, ApiErrorCode.AU1001)
        .err(404, ApiErrorCode.NF1004)
        .err(503, ApiErrorCode.OP0000)
        .get()
    ),
)
def delete_scim_user(user_id: str, request: Request, service: DomainService = DomainService.scope()) -> Response:
    Auth.ensure_scim_authorized(request.headers)
    user = service.scim_provisioning.resolve_user(user_id)
    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    try:
        service.scim_provisioning.delete_user(user)
    except ScimProvisioningException.Unavailable as error:
        raise ApiException.ServiceUnavailable_503(ApiErrorCode.OP0000) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
