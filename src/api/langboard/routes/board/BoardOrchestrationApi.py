from typing import Any
from fastapi import status
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import (
    ApiErrorCode,
    ApiException,
    ApiPermission,
    AppRouter,
    BaseFormModel,
    JsonResponse,
    form_model,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, Card, ProjectColumn, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.filter import RoleFilter
from langboard_shared.security import Auth, RoleFinder
from pydantic import Field


@form_model
class OrchestrationTaskMetadataForm(BaseFormModel):
    source: str | None = Field(default=None, title="Task source")
    source_url: str | None = Field(default=None, title="Task source URL")
    external_id: str | None = Field(default=None, title="External task ID")
    type: str | None = Field(default=None, title="Task type")
    assigned_agent: str | None = Field(default=None, title="Assigned agent role")
    assigned_bot_uid: str | None = Field(default=None, title="Assigned bot UID")
    acceptance_criteria: list[str] | None = Field(default=None, title="Acceptance criteria")
    risk_level: str | None = Field(default=None, title="Task risk level")
    related_files: list[str] | None = Field(default=None, title="Related files")
    pr_url: str | None = Field(default=None, title="Pull request URL")


@form_model
class CreateOrchestrationTaskForm(BaseFormModel):
    title: str = Field(..., title="Task title")
    project_column_uid: str | None = Field(default=None, title="Target column UID")
    description: EditorContentModel | None = Field(default=None, title="Task description")
    assign_users: list[str] | None = Field(default=None, title="Assigned user UIDs")
    metadata: OrchestrationTaskMetadataForm | None = Field(default=None, title="Task metadata")


@form_model
class OrchestrationTaskFailureForm(BaseFormModel):
    status: str | None = Field(default=None, title="Failure status")
    summary: str | None = Field(default=None, title="Failure summary")
    cause: str | None = Field(default=None, title="Failure cause")
    reproduction: list[str] | None = Field(default=None, title="Reproduction steps")
    recommendation: list[str] | None = Field(default=None, title="Recommended fixes")
    auto_fix: bool | None = Field(default=None, title="Move to auto-fix workflow")


@form_model
class OrchestrationTaskSuggestionForm(BaseFormModel):
    title: str = Field(..., title="Suggestion title")
    type: str | None = Field(default=None, title="Task type")
    assigned_agent: str | None = Field(default=None, title="Assigned agent role")
    assigned_bot_uid: str | None = Field(default=None, title="Assigned bot UID")
    risk_level: str | None = Field(default=None, title="Risk level")
    acceptance_criteria: list[str] | None = Field(default=None, title="Acceptance criteria")
    related_files: list[str] | None = Field(default=None, title="Related files")
    created_card_uid: str | None = Field(default=None, title="Created child card UID")


@form_model
class RecordOrchestrationVerificationForm(BaseFormModel):
    status: str = Field(..., title="Verification status")
    summary: str | None = Field(default=None, title="Verification summary")
    checked_at: str | None = Field(default=None, title="Verification timestamp")
    failure: OrchestrationTaskFailureForm | None = Field(default=None, title="Failure details")
    target_column_name: str | None = Field(default=None, title="Column to move the card to")


@form_model
class RecordOrchestrationRunForm(BaseFormModel):
    status: str = Field(..., title="Run status")
    run_id: str | None = Field(default=None, title="Agent run ID")
    bot_log_uid: str | None = Field(default=None, title="Bot log UID")
    assigned_agent: str | None = Field(default=None, title="Assigned agent role")
    summary: str | None = Field(default=None, title="Run summary")
    started_at: str | None = Field(default=None, title="Run start timestamp")
    finished_at: str | None = Field(default=None, title="Run finish timestamp")


@form_model
class RecordOrchestrationSuggestionsForm(BaseFormModel):
    suggestions: list[OrchestrationTaskSuggestionForm] = Field(..., title="Task suggestions")


@form_model
class CreateOrchestrationSuggestionTaskForm(BaseFormModel):
    suggestion: OrchestrationTaskSuggestionForm = Field(..., title="Suggestion to create as a child task")
    target_column_name: str | None = Field(default=None, title="Target column name")
    relationship_type_uid: str | None = Field(default=None, title="Relationship type UID")


@form_model
class RecordOrchestrationBypassForm(BaseFormModel):
    allowed: bool | None = Field(default=None, title="Whether bypass is allowed")
    reason: str | None = Field(default=None, title="Bypass decision reason")
    risk_level: str | None = Field(default=None, title="Risk level")
    action_type: str | None = Field(default=None, title="Action type")
    requires_approval: bool | None = Field(default=None, title="Whether approval is required")
    thread_id: str | None = Field(default=None, title="Graph thread ID")
    session_id: str | None = Field(default=None, title="Graph session ID")
    run_id: str | None = Field(default=None, title="Graph run ID")
    origin_type: str | None = Field(default=None, title="Approval origin type")
    scope_table: str | None = Field(default=None, title="Approval scope table")
    scope_uid: str | None = Field(default=None, title="Approval scope UID")
    document_name: str | None = Field(default=None, title="Approval document name")
    permission: str | None = Field(default=None, title="Approval permission")
    tool_name: str | None = Field(default=None, title="Approval tool name")
    api_name: str | None = Field(default=None, title="Approval API name")
    preview: dict[str, Any] | None = Field(default=None, title="Approval preview payload")
    request_payload: dict[str, Any] | None = Field(default=None, title="Approval request payload")


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.post(
    "/board/{project_uid}/orchestration/workflow-template",
    tags=["Board.Orchestration"],
    description="Apply the default orchestration workflow columns to a project.",
    responses=OpenApiSchema()
    .suc({"columns": [(ProjectColumn, {"schema": {"count": "integer"}})]})
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2001)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def apply_orchestration_workflow_template(
    project_uid: str,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    columns = service.orchestration_task.apply_workflow_template(user_or_bot, project_uid)
    if columns is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2001)

    return JsonResponse(content={"columns": columns})


@AppRouter.schema(form=CreateOrchestrationTaskForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/orchestration/tasks",
    tags=["Board.Orchestration"],
    description="Create an orchestration task card with task metadata.",
    responses=OpenApiSchema()
    .suc({"card": Card, "metadata": {"key": "value"}}, 201)
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2004)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_orchestration_task(
    project_uid: str,
    form: CreateOrchestrationTaskForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.orchestration_task.create_task(
        user_or_bot,
        project_uid,
        form.title,
        column=form.project_column_uid,
        description=form.description,
        assign_user_uids=form.assign_users,
        metadata=form.metadata.model_dump(exclude_none=True) if form.metadata else {},
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)

    card, metadata = result
    return JsonResponse(content={"card": card, "metadata": metadata}, status_code=status.HTTP_201_CREATED)


@AppRouter.schema(form=RecordOrchestrationVerificationForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/orchestration/card/{card_uid}/verification",
    tags=["Board.Orchestration"],
    description="Record orchestration verification metadata for a card.",
    responses=OpenApiSchema()
    .suc({"metadata": {"key": "value"}})
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2003)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def record_orchestration_verification(
    project_uid: str,
    card_uid: str,
    form: RecordOrchestrationVerificationForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    verification = {
        "status": form.status,
        **({"summary": form.summary} if form.summary else {}),
        **({"checked_at": form.checked_at} if form.checked_at else {}),
    }
    result = service.orchestration_task.record_verification(
        user_or_bot,
        project_uid,
        card_uid,
        verification,
        failure=form.failure.model_dump(exclude_none=True) if form.failure else None,
        target_column_name=form.target_column_name,
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(content={"metadata": result})


@AppRouter.schema(form=RecordOrchestrationRunForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/orchestration/card/{card_uid}/run",
    tags=["Board.Orchestration"],
    description="Record orchestration agent run metadata for a card.",
    responses=OpenApiSchema()
    .suc({"metadata": {"key": "value"}})
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2003)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def record_orchestration_run(
    project_uid: str,
    card_uid: str,
    form: RecordOrchestrationRunForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.orchestration_task.record_run(
        project_uid,
        card_uid,
        form.model_dump(exclude_none=True),
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(content={"metadata": result})


@AppRouter.schema(form=RecordOrchestrationSuggestionsForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/orchestration/card/{card_uid}/suggestions",
    tags=["Board.Orchestration"],
    description="Record orchestration suggestions for a card.",
    responses=OpenApiSchema()
    .suc({"metadata": {"key": "value"}})
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2003)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def record_orchestration_suggestions(
    project_uid: str,
    card_uid: str,
    form: RecordOrchestrationSuggestionsForm,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.orchestration_task.record_suggestions(
        project_uid,
        card_uid,
        [suggestion.model_dump(exclude_none=True) for suggestion in form.suggestions],
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    return JsonResponse(content={"metadata": result})


@AppRouter.schema(form=CreateOrchestrationSuggestionTaskForm, permission=ApiPermission.Create)
@AppRouter.api.post(
    "/board/{project_uid}/orchestration/card/{card_uid}/suggestion-task",
    tags=["Board.Orchestration"],
    description="Create a child task card from an orchestration suggestion.",
    responses=OpenApiSchema()
    .suc({"card": Card, "metadata": {"key": "value"}, "relationships": "object[]"}, 201)
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2004)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def create_orchestration_suggestion_task(
    project_uid: str,
    card_uid: str,
    form: CreateOrchestrationSuggestionTaskForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.orchestration_task.create_child_task_from_suggestion(
        user_or_bot,
        project_uid,
        card_uid,
        form.suggestion.model_dump(exclude_none=True),
        column_name=form.target_column_name,
        relationship_type=form.relationship_type_uid,
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2004)

    card, metadata, relationships = result
    return JsonResponse(
        content={"card": card, "metadata": metadata, "relationships": relationships},
        status_code=status.HTTP_201_CREATED,
    )


@AppRouter.schema(form=RecordOrchestrationBypassForm, permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/board/{project_uid}/orchestration/card/{card_uid}/bypass",
    tags=["Board.Orchestration"],
    description="Record an orchestration bypass dry-run decision for a card.",
    responses=OpenApiSchema()
    .suc({"metadata": {"key": "value"}, "approval_request": {}})
    .auth()
    .forbidden()
    .err(404, ApiErrorCode.NF2003)
    .get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
@AuthFilter.add()
def record_orchestration_bypass(
    project_uid: str,
    card_uid: str,
    form: RecordOrchestrationBypassForm,
    user_or_bot: User | Bot = Auth.scope("all"),
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    result = service.orchestration_task.record_bypass_decision(
        user_or_bot,
        project_uid,
        card_uid,
        form.model_dump(exclude_none=True),
    )
    if result is None:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)

    metadata, approval_request = result
    return JsonResponse(content={"metadata": metadata, "approval_request": approval_request})
