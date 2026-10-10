"""Instance and organization app governance policy settings."""

from typing import Literal
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User
from langboard_shared.domain.services.AppGovernance import (
    AppGovernanceConflict,
    AppGovernanceDenied,
    get_policy,
    save_policy,
)
from langboard_shared.security import Auth
from pydantic import Field


@form_model
class AppGovernanceForm(BaseFormModel):
    mode: Literal["disabled", "approved_only", "personal_allowed"] | None
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def _run(operation, *args):
    try:
        return operation(*args)
    except AppGovernanceDenied as exc:
        raise ApiException.Forbidden_403(ApiErrorCode.PE1001) from exc
    except AppGovernanceConflict as exc:
        raise ApiException.Conflict_409(ApiErrorCode.EX3004) from exc
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc


@AppRouter.api.get("/settings/apps/governance", tags=["AppSettings.AppGovernance"])
@AuthFilter.add("admin")
def get_global_governance(user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(content=_run(get_policy, user))


@AppRouter.api.put("/settings/apps/governance", tags=["AppSettings.AppGovernance"])
@AuthFilter.add("admin")
def put_global_governance(form: AppGovernanceForm, user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(content=_run(save_policy, user, form.mode, form.expected_revision))


@AppRouter.api.get("/settings/apps/governance/organizations/{uid}", tags=["AppSettings.AppGovernance"])
@AuthFilter.add("user")
def get_organization_governance(uid: str, user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(content=_run(get_policy, user, SnowflakeID.from_short_code(uid)))


@AppRouter.api.put("/settings/apps/governance/organizations/{uid}", tags=["AppSettings.AppGovernance"])
@AuthFilter.add("user")
def put_organization_governance(uid: str, form: AppGovernanceForm, user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(
        content=_run(save_policy, user, form.mode, form.expected_revision, SnowflakeID.from_short_code(uid))
    )
