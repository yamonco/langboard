from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.WorkflowStageService import WorkflowStageEditConflict
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from sqlalchemy.exc import IntegrityError
from .Form import DeactivateWorkflowStageForm, SaveWorkflowStageForm


@AppRouter.api.get("/settings/workflow-stages", tags=["AppSettings.WorkflowStage"])
@RoleFilter.add(SettingRole, [SettingRoleAction.WorkflowStageRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_workflow_stages(service: DomainService = DomainService.scope()) -> JsonResponse:
    return JsonResponse(content={"stages": service.workflow_stage.get_api_list()})


def _save(form: SaveWorkflowStageForm, service: DomainService, uid: str | None = None) -> JsonResponse:
    if uid and form.expected_revision is None:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
    try:
        stage = service.workflow_stage.save(form.model_dump(), uid)
    except WorkflowStageEditConflict as exc:
        raise ApiException.Conflict_409(ApiErrorCode.EX3004) from exc
    except (ValueError, IntegrityError) as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    if not stage:
        raise ApiException.NotFound_404(ApiErrorCode.NF3003)
    return JsonResponse(content={"stage": stage.api_response()}, status_code=200 if uid else 201)


@AppRouter.api.post("/settings/workflow-stages", tags=["AppSettings.WorkflowStage"])
@RoleFilter.add(SettingRole, [SettingRoleAction.WorkflowStageCreate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def create_workflow_stage(form: SaveWorkflowStageForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    return _save(form, service)


@AppRouter.api.put("/settings/workflow-stages/{stage_uid}", tags=["AppSettings.WorkflowStage"])
@RoleFilter.add(SettingRole, [SettingRoleAction.WorkflowStageUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def update_workflow_stage(
    stage_uid: str, form: SaveWorkflowStageForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    return _save(form, service, stage_uid)


@AppRouter.api.post("/settings/workflow-stages/{stage_uid}/deactivate", tags=["AppSettings.WorkflowStage"])
@RoleFilter.add(SettingRole, [SettingRoleAction.WorkflowStageDeactivate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def deactivate_workflow_stage(
    stage_uid: str, form: DeactivateWorkflowStageForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    try:
        stage = service.workflow_stage.deactivate(stage_uid, form.expected_revision)
    except WorkflowStageEditConflict as exc:
        raise ApiException.Conflict_409(ApiErrorCode.EX3004) from exc
    if not stage:
        raise ApiException.NotFound_404(ApiErrorCode.NF3003)
    return JsonResponse(content={"stage": stage.api_response()})
