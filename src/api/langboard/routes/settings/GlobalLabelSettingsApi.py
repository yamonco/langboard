from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from sqlalchemy.exc import IntegrityError
from .Form import SaveGlobalLabelForm


@AppRouter.api.get("/settings/global-labels", tags=["AppSettings.GlobalLabel"])
@RoleFilter.add(SettingRole, [SettingRoleAction.GlobalLabelRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_global_labels(service: DomainService = DomainService.scope()) -> JsonResponse:
    return JsonResponse(content={"labels": service.global_label.get_api_list()})


def _save(form: SaveGlobalLabelForm, service: DomainService, uid: str | None = None) -> JsonResponse:
    try:
        label = service.global_label.save(form.name, form.color, form.description, uid, form.translations, form.emoji)
    except (ValueError, IntegrityError) as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    if not label:
        raise ApiException.NotFound_404(ApiErrorCode.NF3003)
    return JsonResponse(content={"label": label.api_response()}, status_code=200 if uid else 201)


@AppRouter.api.post("/settings/global-labels", tags=["AppSettings.GlobalLabel"])
@RoleFilter.add(SettingRole, [SettingRoleAction.GlobalLabelCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def create_global_label(form: SaveGlobalLabelForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    return _save(form, service)


@AppRouter.api.put("/settings/global-labels/{label_uid}", tags=["AppSettings.GlobalLabel"])
@RoleFilter.add(SettingRole, [SettingRoleAction.GlobalLabelUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_global_label(
    label_uid: str, form: SaveGlobalLabelForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    return _save(form, service, label_uid)
