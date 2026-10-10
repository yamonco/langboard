"""Native execution review uses the REST receipt transaction, never a call chain."""

from datetime import datetime
from typing import Annotated, Any
from langboard_shared.core.routing import ApiErrorCode, ApiException
from langboard_shared.domain.models import Card, Project, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import RoleFinder
from pydantic import Field
from ..card_workspace.application.execution_receipts import (
    ExecutionArtifact,
    ExecutionChecklistEvidence,
    ExecutionEvidence,
    ExecutionReviewReport,
    PutExecutionReceiptForm,
    receipt_history,
    store_execution_receipt,
)
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(
    "user",
    description="Submit changed/verified/remaining and evidence for the current native execution generation. Atomic receipt plus explicitly configured review move. Retry with the same key and report; no automatic acceptance or human checklist completion. Requires an existing execution generation, not a new claim.",
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def submit_card_execution_review(
    project_uid: str,
    card_uid: str,
    generation: Annotated[int, Field(strict=True, ge=1)],
    idempotency_key: Annotated[str, Field(min_length=1, max_length=300)],
    report: ExecutionReviewReport,
    occurred_at: Annotated[str, Field(min_length=1, max_length=100)],
    user: User,
    artifacts: Annotated[list[ExecutionArtifact], Field(max_length=50)] | None = None,
    checklist_evidence: Annotated[list[ExecutionChecklistEvidence], Field(max_length=200)] | None = None,
) -> dict[str, Any]:
    timestamp = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("occurred_at must include a UTC offset")
    form = PutExecutionReceiptForm(
        status="review_ready",
        summary=report.changed,
        review=report,
        evidence=[ExecutionEvidence(kind="review_report", refs=report.evidence_refs)],
        artifacts=artifacts or [],
        checklist_evidence=checklist_evidence or [],
        occurred_at=timestamp,
    )
    return store_execution_receipt(project_uid, card_uid, generation, form, idempotency_key, user)


@McpTool.add(
    "user",
    description="Read native execution receipts and machine evidence without changing acceptance or human checklists.",
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_execution_receipts(project_uid: str, card_uid: str) -> dict[str, Any]:
    records = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not records:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    _, card = records
    return {"receipts": receipt_history(card.id)}
