from fastapi import Depends
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import GraphApprovalRequest, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.GraphApprovalRequestService import GraphApprovalResumeError
from langboard_shared.filter import RoleFilter
from langboard_shared.publishers import GraphApprovalPublisher
from langboard_shared.security import Auth, RoleFinder
from .forms import GraphApprovalListForm, RejectGraphApprovalForm


@AppRouter.schema(query=GraphApprovalListForm, permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/graph-approvals",
    tags=["Board.GraphApproval"],
    responses=(
        OpenApiSchema()
        .suc({"approvals": [GraphApprovalRequest]})
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def get_graph_approvals(
    project_uid: str, form: GraphApprovalListForm = Depends(), service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    approvals = service.graph_approval_request.get_api_list_by_project(
        project, form.status, form.origin_type, form.scope_table, form.scope_uid, form.limit
    )
    return JsonResponse(content={"approvals": approvals})


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/board/{project_uid}/graph-approvals/count",
    tags=["Board.GraphApproval"],
    responses=OpenApiSchema().suc({"count": "integer"}).auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add("user")
def count_pending_graph_approvals(
    project_uid: str, board_scope_only: bool = False, service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse(
        content={
            "count": service.graph_approval_request.count_pending_by_project(project, board_scope_only=board_scope_only)
        }
    )


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/board/{project_uid}/graph-approval/{approval_uid}/approve",
    tags=["Board.GraphApproval"],
    responses=(
        OpenApiSchema().suc({"approval": GraphApprovalRequest}).auth().forbidden().err(404, ApiErrorCode.NF2022).get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def approve_graph_approval(
    project_uid: str, approval_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    try:
        approval = service.graph_approval_request.approve(approval_uid, user, project)
    except GraphApprovalResumeError as error:
        raise ApiException.BadGateway_502(ApiErrorCode.OP3001) from error
    if not approval:
        raise ApiException.NotFound_404(ApiErrorCode.NF2022)

    approval_response = service.graph_approval_request.get_api_response(approval)
    GraphApprovalPublisher.updated(project, approval_response)
    return JsonResponse(content={"approval": approval_response})


@AppRouter.schema(form=RejectGraphApprovalForm, permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/board/{project_uid}/graph-approval/{approval_uid}/reject",
    tags=["Board.GraphApproval"],
    responses=(
        OpenApiSchema().suc({"approval": GraphApprovalRequest}).auth().forbidden().err(404, ApiErrorCode.NF2022).get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def reject_graph_approval(
    project_uid: str,
    approval_uid: str,
    form: RejectGraphApprovalForm,
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    try:
        approval = service.graph_approval_request.reject(approval_uid, user, form.reason, project)
    except GraphApprovalResumeError as error:
        raise ApiException.BadGateway_502(ApiErrorCode.OP3001) from error
    if not approval:
        raise ApiException.NotFound_404(ApiErrorCode.NF2022)

    approval_response = service.graph_approval_request.get_api_response(approval)
    GraphApprovalPublisher.updated(project, approval_response)
    return JsonResponse(content={"approval": approval_response})
