"""Native global membership settings; only installation administrators may edit."""

from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.domain.services import DomainService
from pydantic import Field


@form_model
class EmployeeMembershipForm(BaseFormModel):
    group_uids: list[str] = Field(max_length=200)


@AppRouter.api.get("/settings/employee-membership", tags=["AppSettings.Identity"])
@AuthFilter.add("admin")
def get_employee_membership(service: DomainService = DomainService.scope()) -> JsonResponse:
    return JsonResponse(content=service.scim_provisioning.get_employee_membership_settings())


@AppRouter.api.put("/settings/employee-membership", tags=["AppSettings.Identity"])
@AuthFilter.add("admin")
def update_employee_membership(
    form: EmployeeMembershipForm, service: DomainService = DomainService.scope()
) -> JsonResponse:
    try:
        return JsonResponse(content=service.scim_provisioning.save_employee_membership_settings(form.group_uids))
    except ValueError:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
