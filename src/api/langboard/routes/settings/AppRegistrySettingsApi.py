"""Instance administrator approval for separately hosted external applications."""

from typing import Any
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.domain.models import User
from langboard_shared.domain.services.AppRegistry import (
    AppRegistryConflict,
    AppRegistryDenied,
    disable_definition,
    list_definitions,
    save_definition,
)
from langboard_shared.security import Auth
from pydantic import Field
from sqlalchemy.exc import IntegrityError


@form_model
class SaveAppDefinitionForm(BaseFormModel):
    declaration: dict[str, Any]
    expected_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@form_model
class DisableAppDefinitionForm(BaseFormModel):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def _run(operation, *args):
    try:
        return operation(*args)
    except AppRegistryDenied as exc:
        raise ApiException.Forbidden_403(ApiErrorCode.PE1001) from exc
    except (AppRegistryConflict, IntegrityError) as exc:
        raise ApiException.Conflict_409(ApiErrorCode.EX3004) from exc
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc


@AppRouter.api.get("/settings/apps/registry", tags=["AppSettings.AppRegistry"])
@AuthFilter.add("admin")
def get_app_definitions(user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(content={"apps": _run(list_definitions, user)})


@AppRouter.api.post("/settings/apps/registry", tags=["AppSettings.AppRegistry"])
@AuthFilter.add("admin")
def approve_app_definition(form: SaveAppDefinitionForm, user: User = Auth.scope("user")) -> JsonResponse:
    return JsonResponse(content={"app": _run(save_definition, user, form.declaration, form.expected_revision)})


@AppRouter.api.post("/settings/apps/registry/{app_key}/disable", tags=["AppSettings.AppRegistry"])
@AuthFilter.add("admin")
def disable_app_definition(app_key: str, form: DisableAppDefinitionForm, user: User = Auth.scope("user")) -> JsonResponse:
    result = _run(disable_definition, user, app_key, form.expected_revision)
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF3003)
    return JsonResponse(content={"app": result})
