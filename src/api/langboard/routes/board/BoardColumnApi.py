from fastapi import status
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    ApiPermission,
    AppRouter,
    EEditorCollaborationType,
    JsonResponse,
    collaborative_block,
    collaborative_edit,
    collaborative_text,
    create_editor_collaboration_document_id,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, ProjectColumn, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from .forms import ChangeRootOrderForm, ColumnDescriptionForm, ColumnForm, CreateColumnForm


@AppRouter.schema(form=CreateColumnForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/column",
    tags=["Board.Column"],
    description="Create a project column.",
    responses=(
        OpenApiSchema()
        .suc({"column": (ProjectColumn, {"schema": {"count": "integer"}})}, 201)
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF2001)
        .get()
    ),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def create_project_column(
    project_uid: str,
    form: CreateColumnForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    column = service.project_column.create(user_or_bot, project_uid, form.name, description=form.description)
    if not column:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse(
        content={
            "column": {
                **column.api_response(),
                "count": 0,
            }
        },
        status_code=status.HTTP_201_CREATED,
    )


@collaborative_edit(
    collaborative_text(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BoardColumnName, "{project_uid}", "{column_uid}"
        ),
        "name",
        "name",
    )
)
@AppRouter.schema(form=ColumnForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/column/{column_uid}/name",
    tags=["Board.Column"],
    description="Change project column name.",
    responses=OpenApiSchema().suc({"name": "string"}).auth().forbidden().err(404, ApiErrorCode.NF2004).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def update_project_column_name(
    project_uid: str,
    column_uid: str,
    form: ColumnForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_column.change_name(user_or_bot, project_uid, column_uid, form.name)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)

    return JsonResponse(content={"name": form.name})


@AppRouter.schema(form=ColumnDescriptionForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/column/{column_uid}/description",
    tags=["Board.Column"],
    description="Change workflow guidance without renaming a column or moving cards.",
    responses=OpenApiSchema().suc({"description": "string"}).auth().forbidden().err(404, ApiErrorCode.NF2004).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def update_project_column_description(
    project_uid: str,
    column_uid: str,
    form: ColumnDescriptionForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    """Require existing board update authorization for workflow guidance edits."""
    if not service.project_column.change_description(project_uid, column_uid, form.description):
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)
    return JsonResponse(content={"description": form.description})


@AppRouter.api.put(
    "/board/{project_uid}/column/{column_uid}/order",
    tags=["Board.Column"],
    description="Change project column order.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2004).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add("user")
def update_project_column_order(
    project_uid: str,
    column_uid: str,
    form: ChangeRootOrderForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_column.change_order(project_uid, column_uid, form.order)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)

    return JsonResponse()


@collaborative_edit(
    collaborative_block(
        create_editor_collaboration_document_id(
            EEditorCollaborationType.BoardColumnName, "{project_uid}", "{column_uid}"
        )
    )
)
@AppRouter.schema(permission=ApiPermission.Delete)
@AppRouter.api.delete(
    "/board/{project_uid}/column/{column_uid}",
    tags=["Board.Column"],
    description="Delete a project column.",
    responses=OpenApiSchema().auth().forbidden().err(404, ApiErrorCode.NF2004).get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def delete_project_column(
    project_uid: str,
    column_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.project_column.delete(user_or_bot, project_uid, column_uid)
    if not result:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)

    return JsonResponse()
