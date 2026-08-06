from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.domain.services import DomainService
from .Form import SetDefaultProjectTemplateForm


@AppRouter.api.get("/settings/project-templates", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("admin")
def get_project_templates(service: DomainService = DomainService.scope()) -> JsonResponse:
    """List reusable project templates and the current default."""

    return JsonResponse(content={"templates": service.project_template.get_api_list()})


@AppRouter.api.put("/settings/project-templates/default", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("admin")
def set_default_project_template(
    form: SetDefaultProjectTemplateForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Select the template used when project creation omits a template."""

    template = service.project_template.set_default(form.template_name)
    return JsonResponse(content={"template": template.api_response()})
