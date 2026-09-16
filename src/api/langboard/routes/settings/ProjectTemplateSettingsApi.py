from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from .Form import SetDefaultProjectTemplateForm


@AppRouter.api.get("/settings/project-templates", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("user")
def get_project_templates(service: DomainService = DomainService.scope()) -> JsonResponse:
    """List non-sensitive reusable project templates for project creation."""

    return JsonResponse(content={"templates": service.project_template.get_api_list()})


@AppRouter.api.put("/settings/project-templates/default", tags=["AppSettings.ProjectTemplate"])
@RoleFilter.add(
    SettingRole,
    [SettingRoleAction.ProjectTemplateUpdate],
    RoleFinder.setting,
    allowed_all_admin=False,
)
@AuthFilter.add("admin")
def set_default_project_template(
    form: SetDefaultProjectTemplateForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Select the template used when project creation omits a template."""

    try:
        template = service.project_template.set_default(form.template_name)
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    return JsonResponse(content={"template": template.api_response()})
