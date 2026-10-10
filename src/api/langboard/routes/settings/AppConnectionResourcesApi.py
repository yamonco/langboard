"""Credential-scoped external resources. No user identity supplied by callers."""

from fastapi import Header, Query
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services.AppConnectionResources import (
    AppResourceCredentialDenied,
    list_connection_resources,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied


@AppRouter.api.get("/apps/v1/boards/{project_uid}/resources", tags=["App.Resources"])
def app_resources(
    project_uid: str,
    authorization: str = Header(default="", max_length=256),
    after: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9]{11}$"),
    limit: int = Query(default=25, ge=1, le=50),
) -> JsonResponse:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = list_connection_resources(
            token,
            SnowflakeID.from_short_code(project_uid),
            after_id=SnowflakeID.from_short_code(after) if after else None,
            limit=limit,
        )
    except AppResourceCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})
