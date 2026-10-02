from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.domain.services import DomainService
from sqlalchemy.exc import IntegrityError
from .Form import SaveProjectTemplateForm, SetDefaultProjectTemplateForm


@AppRouter.api.get("/settings/project-templates", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("user")
def get_project_templates(service: DomainService = DomainService.scope()) -> JsonResponse:
    """List non-sensitive reusable project templates for project creation."""

    return JsonResponse(content={"templates": service.project_template.get_api_list()})


@AppRouter.api.put("/settings/project-templates/default", tags=["AppSettings.ProjectTemplate"])
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


def _save_structure(form: SaveProjectTemplateForm, service: DomainService, uid: str | None = None) -> JsonResponse:
    try:
        template = service.project_template.save_columns(
            form.name,
            [column.model_dump() for column in form.columns],
            uid,
            description=form.description,
            global_label_uids=form.global_label_uids,
            internal_bot_uids=form.internal_bot_uids,
        )
    except (ValueError, IntegrityError) as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    if not template:
        raise ApiException.NotFound_404(ApiErrorCode.NF3003)
    return JsonResponse(content={"template": template.api_response()}, status_code=200 if uid else 201)


@AppRouter.api.post("/settings/project-templates", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("admin")
def create_project_template(
    form: SaveProjectTemplateForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    return _save_structure(form, service)


@AppRouter.api.put("/settings/project-templates/{template_uid}", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("admin")
def update_project_template(
    template_uid: str, form: SaveProjectTemplateForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    return _save_structure(form, service, template_uid)


@AppRouter.api.get("/settings/project-template-bots", tags=["AppSettings.ProjectTemplate"])
@AuthFilter.add("admin")
def get_project_template_bots(service: DomainService = DomainService.scope()) -> JsonResponse:
    """Return selection identities only, excluding credentials and prompts."""
    bots = service.internal_bot.get_api_list(is_setting=False)
    return JsonResponse(
        content={"bots": [{key: bot[key] for key in ("uid", "bot_type", "display_name")} for bot in bots]}
    )
