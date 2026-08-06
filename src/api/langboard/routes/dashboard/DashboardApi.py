from fastapi import Depends, status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Card, Checkitem, Project, ProjectColumn, User
from langboard_shared.domain.services import DomainService
from langboard_shared.security import Auth
from .DashboardForm import DashboardPagination, DashboardProjectCreateForm


@AppRouter.api.get(
    "/dashboard/user/projects/starred",
    tags=["Dashboard"],
    responses=(
        OpenApiSchema()
        .suc({"projects": [(Project, {"schema": {"starred": "bool", "last_viewed_at": "string"}})]})
        .auth()
        .forbidden()
        .get()
    ),
)
@AuthFilter.add("user")
def get_starred_projects(
    user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    projects = service.project.get_api_starred_project_list(user)

    return JsonResponse(content={"projects": projects})


@AppRouter.api.get(
    "/dashboard/projects",
    tags=["Dashboard"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "projects": [
                    (
                        Project,
                        {
                            "schema": {
                                "starred": "bool",
                                "last_viewed_at": "string",
                            }
                        },
                    ),
                ],
                "columns": [(ProjectColumn, {"schema": {"count": "integer"}})],
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@AuthFilter.add("user")
def get_projects(user: User = Auth.scope("user"), service: DomainService = DomainService.scope()) -> JsonResponse:
    projects, columns = service.project.get_api_list_with_columns(user)

    return JsonResponse(content={"projects": projects, "columns": columns})


@AppRouter.api.post(
    "/dashboard/projects/new",
    tags=["Dashboard"],
    responses=OpenApiSchema().suc({"project_uid": "string"}, 201).auth().forbidden().get(),
)
@AuthFilter.add("user")
def create_project(
    form: DashboardProjectCreateForm, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
):
    try:
        project, _, _ = service.project_template.create_project(
            user,
            form.title,
            form.description,
            form.project_type,
            form.template_name,
        )
    except ValueError as exc:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000) from exc
    return JsonResponse(content={"project_uid": project.get_uid()}, status_code=status.HTTP_201_CREATED)


@AppRouter.api.put(
    "/dashboard/projects/{project_uid}/star",
    tags=["Dashboard"],
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2001).get(),
)
@AuthFilter.add("user")
def toggle_star_project(
    project_uid: str, user: User = Auth.scope("user"), service: DomainService = DomainService.scope()
) -> JsonResponse:
    result = service.project.toggle_star(user, project_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse()


@AppRouter.api.get(
    "/dashboard/cards",
    tags=["Dashboard"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "cards": [(Card, {"schema": {"project_column_name": "string"}})],
                "projects": [Project],
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@AuthFilter.add("user")
def get_card_list(
    pagination: DashboardPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    cards, projects = service.card.get_dashboard_list(user, pagination)

    return JsonResponse(content={"cards": cards, "projects": projects})


@AppRouter.api.get(
    "/dashboard/tracking",
    tags=["Dashboard"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "checkitems": [
                    (
                        Checkitem,
                        {
                            "schema": {
                                "card_uid": "string",
                                "initial_timer_started_at": "string",
                                "timer_started_at": "string",
                            }
                        },
                    ),
                ],
                "cards": [Card],
                "projects": [Project],
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@AuthFilter.add("user")
def track_checkitems(
    pagination: DashboardPagination = Depends(),
    user: User = Auth.scope("user"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    checkitems, cards, projects = service.checkitem.get_tracking_list(user, pagination)

    return JsonResponse(content={"checkitems": checkitems, "cards": cards, "projects": projects})
