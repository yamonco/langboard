"""Dedicated app identity endpoint; cannot authenticate as a user or bot."""

from fastapi import Header
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services.AppConnectionAuthentication import authenticate_connection_credential
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied


@AppRouter.api.get("/apps/v1/identity", tags=["App.Identity"])
def app_identity(authorization: str = Header(default="", max_length=256)) -> JsonResponse:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiException.Unauthorized_401()
    try:
        principal = authenticate_connection_credential(token)
    except AppGovernanceDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    return JsonResponse(
        content={
            "schema_version": 1,
            "app_key": principal.app_key,
            "connection_uid": SnowflakeID(principal.connection_id).to_short_code(),
            "credential_uid": SnowflakeID(principal.credential_id).to_short_code(),
            "organization_uid": SnowflakeID(principal.organization_id).to_short_code()
            if principal.organization_id
            else None,
        },
        headers={"Cache-Control": "no-store"},
    )
