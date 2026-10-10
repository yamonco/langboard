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

@form_model
class BoardAppConsentForm(BaseFormModel):
    model_config = {"extra": "forbid"}
    app_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_uid: str = Field(pattern=r"^[A-Za-z0-9]{11}$")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    capabilities: list[str] = Field(max_length=32)


@AppRouter.api.put("/board/{project_uid}/settings/apps/{app_key}/consent", tags=["Board.Apps"])
@AuthFilter.add("user")
def save_board_app_consent(
    project_uid: str, app_key: str, form: BoardAppConsentForm, user: User = Auth.scope("user")
) -> JsonResponse:
    from langboard_shared.domain.services import DomainService
    from langboard_shared.domain.services.AppRegistry import set_board_consent

    service = DomainService()
    try:
        result = _run(
            set_board_consent,
            service.workflow_stage,
            user,
            project_uid,
            app_key,
            form.app_revision,
            form.binding_uid,
            form.expected_revision,
            form.capabilities,
        )
        return JsonResponse(content=result)
    finally:
        service.close()
