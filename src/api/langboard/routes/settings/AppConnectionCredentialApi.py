"""Explicit owner-managed inbound app credentials. Responses are never cached."""

from fastapi import Query
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from langboard_shared.domain.services.AppConnectionAuthentication import (
    issue_connection_credential,
    list_connection_credentials,
    revoke_connection_credential,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.security import Auth
from pydantic import Field


@form_model
class IssueCredentialForm(BaseFormModel):
    expires_in_seconds: int = Field(default=3600, strict=True, ge=60, le=86400)


def _run(operation, *args, **kwargs):
    try:
        return JsonResponse(content=operation(*args, **kwargs), headers={"Cache-Control": "no-store"})
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403(ApiErrorCode.PE1001) from exc


@AppRouter.api.post("/settings/apps/connections/{connection_uid}/credentials", tags=["AppSettings.Credentials"])
@AuthFilter.add("user")
def issue_credential(connection_uid: str, form: IssueCredentialForm, user: User = Auth.scope("user")) -> JsonResponse:
    return _run(
        issue_connection_credential,
        user,
        SnowflakeID.from_short_code(connection_uid),
        expires_in_seconds=form.expires_in_seconds,
    )


@AppRouter.api.get("/settings/apps/connections/{connection_uid}/credentials", tags=["AppSettings.Credentials"])
@AuthFilter.add("user")
def list_credentials(
    connection_uid: str,
    user: User = Auth.scope("user"),
    after: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9]{11}$"),
    limit: int = Query(default=25, ge=1, le=50),
) -> JsonResponse:
    return _run(
        list_connection_credentials,
        user,
        SnowflakeID.from_short_code(connection_uid),
        after_id=SnowflakeID.from_short_code(after) if after else None,
        limit=limit,
    )


@AppRouter.api.post(
    "/settings/apps/connections/{connection_uid}/credentials/{credential_uid}/revoke", tags=["AppSettings.Credentials"]
)
@AuthFilter.add("user")
def revoke_credential(connection_uid: str, credential_uid: str, user: User = Auth.scope("user")) -> JsonResponse:
    return _run(
        revoke_connection_credential,
        user,
        SnowflakeID.from_short_code(connection_uid),
        SnowflakeID.from_short_code(credential_uid),
    )
