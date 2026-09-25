"""Native, idempotent execution receipts for a board card generation."""

from datetime import datetime
from hashlib import sha256
from json import dumps
from typing import Literal
from urllib.parse import urlsplit
from fastapi import Header
from langboard_shared.core.db import DbSession
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
from langboard_shared.domain.models import Card, Project, ProjectRole
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import RoleFinder
from langboard_shared.tasks.webhooks.ExecutionReadinessUow import current_execution, execution_readiness_uow
from pydantic import Field, field_validator
from sqlalchemy import select, text


class ExecutionArtifact(BaseFormModel):
    type: Literal["pull_request", "run", "log", "url"]
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Artifact URL must use HTTP or HTTPS")
        return value


class ExecutionEvidence(BaseFormModel):
    kind: str = Field(min_length=1, max_length=100)
    refs: list[str] = Field(default_factory=list, max_length=50)


class ExecutionChecklistEvidence(ExecutionEvidence):
    item_uid: str = Field(min_length=1, max_length=100)


@form_model
class PutExecutionReceiptForm(BaseFormModel):
    status: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=4000)
    artifacts: list[ExecutionArtifact] = Field(default_factory=list, max_length=50)
    evidence: list[ExecutionEvidence] = Field(default_factory=list, max_length=100)
    checklist_evidence: list[ExecutionChecklistEvidence] = Field(default_factory=list, max_length=200)
    occurred_at: datetime


def _receipt_rows(db: DbSession, card_id: int):
    return db.exec(
        select(
            text("execution_generation"),
            text("idempotency_key"),
            text("payload_json"),
            text("created_at"),
        )
        .select_from(text("execution_receipt"))
        .where(text("card_id = :card_id"))
        .order_by(text("execution_generation DESC")),
        params={"card_id": card_id},
    ).all()


def receipt_history(card_id: int) -> list[dict]:
    with DbSession.use(readonly=False) as db:
        projections = db.exec(
            select(
                text("execution_generation"),
                text("item_uid"),
                text("evidence_kind"),
                text("evidence_refs"),
                text("is_checked"),
            )
            .select_from(text("execution_checklist_projection"))
            .where(text("card_id = :card_id"))
            .order_by(text("execution_generation DESC, item_uid")),
            params={"card_id": card_id},
        ).all()
        by_generation: dict[int, list[dict]] = {}
        for generation, item_uid, kind, refs, is_checked in projections:
            by_generation.setdefault(generation, []).append(
                {"item_uid": item_uid, "kind": kind, "refs": refs, "is_checked": is_checked}
            )
        return [
            {
                "generation": generation,
                "idempotency_key": key,
                "receipt": payload,
                "checklist_projection": by_generation.get(generation, []),
                "created_at": created_at.isoformat(),
            }
            for generation, key, payload, created_at in _receipt_rows(db, card_id)
        ]


def _reconcile_machine_checklist(db: DbSession, card_id: int, generation: int, payload: dict) -> None:
    """Project only receipt evidence; never mutate user-authored checkitems.

    A matching PR artifact and `pr_submitted` claim form the one deterministic
    auto-check rule. Other claims stay visible but unchecked for human review.
    Retrying a saved receipt recreates a missing projection row without toggles.
    """
    pr_urls = {artifact["url"] for artifact in payload["artifacts"] if artifact["type"] == "pull_request"}
    reviewable = payload["status"] in {"review_ready", "completed", "success"}
    for evidence in payload["checklist_evidence"]:
        checked = reviewable and evidence["kind"] == "pr_submitted" and bool(
            pr_urls.intersection(evidence["refs"])
        )
        db.exec(
            text("""
                INSERT INTO execution_checklist_projection(
                    card_id, execution_generation, item_uid, evidence_kind, evidence_refs, is_checked
                ) VALUES (
                    :card_id, :generation, :item_uid, :kind, CAST(:refs AS jsonb), :checked
                ) ON CONFLICT (card_id, execution_generation, item_uid) DO UPDATE SET
                    evidence_kind = EXCLUDED.evidence_kind,
                    evidence_refs = EXCLUDED.evidence_refs,
                    is_checked = EXCLUDED.is_checked
            """),
            params={
                "card_id": card_id,
                "generation": generation,
                "item_uid": evidence["item_uid"],
                "kind": evidence["kind"],
                "refs": dumps(evidence["refs"]),
                "checked": checked,
            },
        )


def _move_to_review(db: DbSession, card_id: int, project_id: int) -> bool:
    row = db.exec(
        select(text("is_enabled"), text("column_semantic_ids"))
        .select_from(text("project_execution_binding"))
        .where(text("project_id = :project_id")),
        params={"project_id": project_id},
    ).first()
    if row is None or not row[0] or not isinstance(row[1], dict):
        return False
    try:
        review_ids = [int(column_id) for column_id, semantic in row[1].items() if semantic == "review"]
    except (TypeError, ValueError):
        return False
    if len(review_ids) != 1:
        return False
    target_id = review_ids[0]
    source = db.exec(
        select(text("project_column_id"))
        .select_from(text("card"))
        .where(text("id = :card_id")),
        params={"card_id": card_id},
    ).first()
    if source is None or row[1].get(str(source[0])) not in {"ready", "active"}:
        return False
    target = db.exec(
        select(text("id"))
        .select_from(text("project_column"))
        .where(text("id = :target_id AND project_id = :project_id AND deleted_at IS NULL AND NOT is_archive")),
        params={"target_id": target_id, "project_id": project_id},
    ).first()
    if target is None:
        return False
    db.exec(
        text("""
            UPDATE card SET project_column_id = :target_id,
                "order" = (SELECT COALESCE(MAX("order"), -1) + 1 FROM card
                           WHERE project_column_id = :target_id AND deleted_at IS NULL),
                updated_at = now()
            WHERE id = :card_id AND project_column_id <> :target_id
        """),
        params={"card_id": card_id, "target_id": target_id},
    )
    return True


@AppRouter.schema(permission=ApiPermission.Edit)
@AppRouter.api.put(
    "/projects/{project_uid}/cards/{card_uid}/executions/{generation}/receipt",
    tags=["Board.Card.Execution"],
    description="Store one receipt per execution generation, separately from the user card description.",
    responses=OpenApiSchema().suc({"receipt": "object", "created": "boolean"}).auth().forbidden().get(),
)
@RoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
@AuthFilter.add()
def put_execution_receipt(
    project_uid: str,
    card_uid: str,
    generation: int,
    form: PutExecutionReceiptForm,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> JsonResponse:
    records = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not records:
        raise ApiException.NotFound_404(ApiErrorCode.NF2003)
    project, card = records
    expected_key = f"langboard:{project_uid}:{card_uid}:{generation}:receipt"
    if generation < 1 or idempotency_key != expected_key:
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
    payload = form.model_dump(mode="json")
    item_uids = [item["item_uid"] for item in payload["checklist_evidence"]]
    if len(item_uids) != len(set(item_uids)):
        raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
    encoded = dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    # The same report can be retried with a new transport timestamp. Identity
    # and semantic content stay fixed; preserve the first occurred_at in storage.
    semantic = {key: value for key, value in payload.items() if key != "occurred_at"}
    content_hash = sha256(dumps(semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    with execution_readiness_uow() as execution:
        db = execution.db
        execution.watch(card.id)
        current = current_execution(card.id, db)
        if current is None or current[2] != generation:
            raise ApiException.Conflict_409()
        inserted = db.exec(
            text("""
                INSERT INTO execution_receipt(
                    project_id, card_id, execution_generation, idempotency_key, content_hash, payload_json
                ) VALUES (
                    :project_id, :card_id, :generation, :key, :content_hash, CAST(:payload AS jsonb)
                ) ON CONFLICT DO NOTHING
            """),
            params={
                "project_id": project.id,
                "card_id": card.id,
                "generation": generation,
                "key": expected_key,
                "content_hash": content_hash,
                "payload": encoded,
            },
        )
        created = bool(inserted)
        saved = db.exec(
            select(text("idempotency_key"), text("content_hash"), text("payload_json"))
            .select_from(text("execution_receipt"))
            .where(text("card_id = :card_id AND execution_generation = :generation")),
            params={"card_id": card.id, "generation": generation},
        ).first()
        if saved is None or saved[0] != expected_key or saved[1] != content_hash:
            raise ApiException.Conflict_409()
        _reconcile_machine_checklist(db, card.id, generation, saved[2])
        if created and payload["status"] in {"review_ready", "completed", "success"}:
            _move_to_review(db, card.id, project.id)
    return JsonResponse(content={"receipt": saved[2], "created": created, "generation": generation})


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
