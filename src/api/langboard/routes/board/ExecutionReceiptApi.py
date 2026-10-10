"""Authorized REST adapters for the shared native execution receipt commands."""

from fastapi import Header
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, ApiPermission, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, Card, Project, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import Auth, RoleFinder
from ...card_workspace.application.execution_receipts import (
    PutExecutionReceiptForm,
    receipt_history,
    store_execution_receipt,
)


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/projects/{project_uid}/cards/{card_uid}/executions/{generation}/receipt",
    tags=["Board.Card.Execution"],
    description="Store one receipt per execution generation, separately from the user card description.",
    responses=OpenApiSchema().suc({"receipt": "object", "created": "boolean"}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def put_execution_receipt(
    project_uid: str,
    card_uid: str,
    generation: int,
    form: PutExecutionReceiptForm,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    user_or_bot: User | Bot = Auth.scope("all"),  # noqa: B008 - FastAPI authentication dependency
) -> JsonResponse:
    return JsonResponse(
        content=store_execution_receipt(project_uid, card_uid, generation, form, idempotency_key, user_or_bot)
    )


@AppRouter.schema(permission=ApiPermission.Read)
@AppRouter.api.get(
    "/projects/{project_uid}/cards/{card_uid}/executions/receipts",
    tags=["Board.Card.Execution"],
    description="Read the card's native execution receipt history.",
    responses=OpenApiSchema().suc({"receipts": "object[]"}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
@AuthFilter.add()
def get_execution_receipts(project_uid: str, card_uid: str) -> JsonResponse:
    records = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not records:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    _, card = records
    return JsonResponse(content={"receipts": receipt_history(card.id)})
