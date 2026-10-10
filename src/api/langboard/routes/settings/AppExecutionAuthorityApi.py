"""Current execution authority inspection; never a running lease or start receipt."""

from fastapi import Header, Query
from langboard_shared.core.routing import ApiException, AppRouter, JsonResponse
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services.AppExecutionGrant import (
    AppExecutionCredentialDenied,
    evaluate_current_execution_grant,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied


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
