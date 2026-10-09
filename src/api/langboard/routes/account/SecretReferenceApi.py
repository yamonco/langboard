"""Authenticated metadata-only secret references for native clients."""

from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.security import Auth


@AppRouter.api.get("/secret-references/{reference_uid}", tags=["Account"], responses=OpenApiSchema().auth().get())
@AuthFilter.add("user")
def get_secret_reference_metadata(
    reference_uid: str,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if len(reference_uid) > 11:
        raise ApiException.NotFound_404()
    try:
        metadata = service.secret_reference.get_metadata(user, f"secret://ref/{reference_uid}")
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.NotFound_404() from None
    return JsonResponse(content={"reference": metadata})


@AppRouter.api.get(
    "/secret-references/{reference_uid}/history", tags=["Account"], responses=OpenApiSchema().auth().get()
)
@AuthFilter.add("user")
def get_secret_reference_history(
    reference_uid: str,
    request: Request,
    limit: int = 25,
    cursor: str | None = None,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not 1 <= len(reference_uid) <= 11 or not 1 <= limit <= 50:
        raise ApiException.NotFound_404()
    try:
        payload = service.secret_reference.list_audit(
            user,
            f"secret://ref/{reference_uid}",
            limit=limit,
            cursor=cursor,
            channel=request.scope.get("collaboration_channel", CollaborationChannel.Api),
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.NotFound_404() from None
    response = JsonResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response
