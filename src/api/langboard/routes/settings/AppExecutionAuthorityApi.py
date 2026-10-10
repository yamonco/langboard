"""Current execution authority inspection; never a running lease or start receipt."""

from fastapi import Header, Query
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services.AppExecutionGrant import (
    AppExecutionCredentialDenied,
    evaluate_current_execution_grant,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from pydantic import BaseModel, ConfigDict, Field


@AppRouter.api.get("/apps/v1/boards/{project_uid}/cards/{card_uid}/execution-authority", tags=["App.Execution"])
def execution_authority(
    project_uid: str,
    card_uid: str,
    generation: int = Query(ge=1),
    authorization: str = Header(default="", max_length=256),
) -> JsonResponse:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = evaluate_current_execution_grant(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(card_uid),
            generation,
        )
    except AppExecutionCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    return JsonResponse(
        content={**result, "state": "eligible", "started": False}, headers={"Cache-Control": "no-store"}
    )


class ExecutionRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(strict=True, ge=1)
    expected_authority_version: str = Field(strict=True, pattern="^[0-9a-f]{64}$")


@AppRouter.api.post("/apps/v1/boards/{project_uid}/cards/{card_uid}/execution-requests", tags=["App.Execution"])
def execution_request(
    project_uid: str,
    card_uid: str,
    body: ExecutionRequestBody,
    authorization: str = Header(default="", max_length=256),
) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict, request_app_execution

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = request_app_execution(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(card_uid),
            body.generation,
            expected_authority_version=body.expected_authority_version,
        )
    except AppExecutionCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    except AppExecutionRequestConflict as exc:
        raise ApiException.Conflict_409() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


@AppRouter.api.get(
    "/apps/v1/boards/{project_uid}/cards/{card_uid}/execution-requests/{request_uid}", tags=["App.Execution"]
)
def execution_request_read(
    project_uid: str, card_uid: str, request_uid: str, authorization: str = Header(default="", max_length=256)
) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionAcknowledgments import read_app_execution_request
    from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = read_app_execution_request(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(card_uid),
            SnowflakeID.from_short_code(request_uid),
        )
    except AppExecutionCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    except AppExecutionRequestConflict as exc:
        raise ApiException.Conflict_409() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


class ExecutionAcknowledgmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_uid: str = Field(strict=True, pattern="^[A-Za-z0-9]{11}$")
    runtime_reference: str = Field(strict=True, min_length=1, max_length=200, pattern=r"\S")


@AppRouter.api.post(
    "/apps/v1/boards/{project_uid}/cards/{card_uid}/execution-requests/{request_uid}/acknowledgments",
    tags=["App.Execution"],
)
def execution_acknowledgment(
    project_uid: str,
    card_uid: str,
    request_uid: str,
    body: ExecutionAcknowledgmentBody,
    authorization: str = Header(default="", max_length=256),
) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionAcknowledgments import acknowledge_app_execution
    from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = acknowledge_app_execution(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(card_uid),
            SnowflakeID.from_short_code(request_uid),
            SnowflakeID.from_short_code(body.event_uid),
            body.runtime_reference,
        )
    except AppExecutionCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    except AppExecutionRequestConflict as exc:
        raise ApiException.Conflict_409() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


class ExecutionPermitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledgment_uid: str = Field(strict=True, pattern="^[A-Za-z0-9]{11}$")
    runtime_token: str = Field(strict=True, pattern="^[0-9a-f]{64}$")


@AppRouter.api.post(
    "/apps/v1/boards/{project_uid}/cards/{card_uid}/execution-requests/{request_uid}/runtime-permits",
    tags=["App.Execution"],
)
def execution_runtime_permit(
    project_uid: str,
    card_uid: str,
    request_uid: str,
    body: ExecutionPermitBody,
    authorization: str = Header(default="", max_length=256),
) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionLeases import authorize_app_runtime
    from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise ApiException.Unauthorized_401()
    try:
        result = authorize_app_runtime(
            token,
            SnowflakeID.from_short_code(project_uid),
            SnowflakeID.from_short_code(card_uid),
            SnowflakeID.from_short_code(request_uid),
            SnowflakeID.from_short_code(body.acknowledgment_uid),
            body.runtime_token,
        )
    except AppExecutionCredentialDenied as exc:
        raise ApiException.Unauthorized_401() from exc
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    except AppExecutionRequestConflict as exc:
        raise ApiException.Conflict_409() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


class RuntimeCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_token: str = Field(strict=True, pattern="^[0-9a-f]{64}$")
    stopped: bool = Field(default=False, strict=True)


class RuntimeRecoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_token: str = Field(strict=True, pattern="^[0-9a-f]{64}$")


@AppRouter.api.post("/apps/v1/execution-requests/{request_uid}/runtime-permit-recovery", tags=["App.Execution"])
def execution_runtime_recovery(request_uid: str, body: RuntimeRecoveryBody) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionLeases import recover_app_runtime

    try:
        result = recover_app_runtime(SnowflakeID.from_short_code(request_uid), body.runtime_token)
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})


@AppRouter.api.post("/apps/v1/runtime-permits/{lease_uid}/check", tags=["App.Execution"])
def execution_runtime_check(lease_uid: str, body: RuntimeCheckBody) -> JsonResponse:
    from langboard_shared.domain.services.AppExecutionLeases import check_app_runtime

    try:
        result = check_app_runtime(SnowflakeID.from_short_code(lease_uid), body.runtime_token, stopped=body.stopped)
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403() from exc
    return JsonResponse(content=result, headers={"Cache-Control": "no-store"})
