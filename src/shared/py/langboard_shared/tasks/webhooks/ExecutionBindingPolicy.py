"""Live fail-closed checks for an opt-in execution webhook binding."""

from ...core.db import DbSession, SqlBuilder
from ...core.security import KeyVault
from ...domain.models import (
    GlobalCardRelationshipType,
    Project,
    ProjectColumn,
    ProjectExecutionBinding,
    WebhookSetting,
)
from ...helpers import InfraHelper


def _lookup(model, uid):
    try:
        return InfraHelper.get_by_id_like(model, uid)
    except (TypeError, ValueError):
        return None


def binding_for_project(project_uid: str) -> ProjectExecutionBinding | None:
    project = _lookup(Project, project_uid)
    if project is None:
        return None
    with DbSession.use(readonly=True) as db:
        return db.exec(
            SqlBuilder.select.table(ProjectExecutionBinding).where(
                ProjectExecutionBinding.column("project_id") == project.id
            )
        ).first()


def binding_invalid_reasons(binding: ProjectExecutionBinding | None, event: str) -> list[str]:
    """Recheck mutable dependencies immediately before queuing or delivering."""

    if binding is None or not binding.is_enabled:
        return ["binding_disabled"]
    reasons: list[str] = []
    project = _lookup(Project, binding.project_id)
    if project is None:
        return ["project_missing"]
    if event not in (binding.events or []):
        reasons.append("event_not_bound")
    webhook = _lookup(WebhookSetting, binding.webhook_uid) if binding.webhook_uid else None
    if webhook is None:
        reasons.append("webhook_missing")
    else:
        if getattr(webhook, "is_enabled", True) is False:
            reasons.append("webhook_disabled")
        if event not in (webhook.events or []):
            reasons.append("event_not_allowed")
        if not webhook.secret_id:
            reasons.append("signing_secret_missing")
        else:
            try:
                if not KeyVault.get_key(webhook.secret_id):
                    reasons.append("signing_secret_unavailable")
            except Exception:
                reasons.append("signing_secret_unavailable")
    semantics = binding.column_semantics or {}
    if not {"ready", "terminal"} <= set(semantics.values()):
        reasons.append("column_semantics_invalid")
    for column_uid in semantics:
        column = _lookup(ProjectColumn, column_uid)
        if column is None or column.project_id != project.id or column.is_archive or column.deleted_at:
            reasons.append("column_invalid")
            break
    relation = (
        _lookup(GlobalCardRelationshipType, binding.prerequisite_relationship_type_uid)
        if binding.prerequisite_relationship_type_uid
        else None
    )
    if relation is None:
        reasons.append("relationship_type_invalid")
    return reasons
