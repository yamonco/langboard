"""Authenticated metadata-only secret references for native clients."""

from fastapi import Request
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import (
    SecretReferenceConflict,
    SecretReferenceUnavailable,
)
from langboard_shared.security import Auth
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError


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
    response = JsonResponse(content={"reference": metadata})
    response.headers["Cache-Control"] = "no-store"
    return response


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


class CopySecretReferenceForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(strict=True, min_length=1, max_length=256)
    expected_revision: int = Field(strict=True, ge=0)


@AppRouter.api.post("/secret-references/{reference_uid}/copy", tags=["Account"])
@AuthFilter.add("user")
def copy_secret_reference(
    reference_uid: str,
    form: CopySecretReferenceForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not 1 <= len(reference_uid) <= 11:
        raise ApiException.NotFound_404()
    try:
        reference = service.secret_reference.copy(
            user, f"secret://ref/{reference_uid}", form.name, form.expected_revision
        )
    except (SecretReferenceUnavailable, ValueError):
        raise ApiException.NotFound_404() from None
    except (SecretReferenceConflict, IntegrityError):
        raise ApiException.Conflict_409() from None
    response = JsonResponse(content={"reference": reference}, status_code=201)
    response.headers["Cache-Control"] = "no-store"
    return response
