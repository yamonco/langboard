"""Current owner-app execution grant; declaration and resource reads are insufficient."""

from hashlib import sha256
from json import dumps
from sqlalchemy import select, text
from ...core.db import DbSession, SqlBuilder
from ...core.types import SnowflakeID
from ..DependencyConditions import BLOCKING_RELATION_JOINS, UNSATISFIED_PREREQUISITE
from ..models import (
    AppConnection,
    AppDefinition,
    AppResourceBinding,
    BoardAppBinding,
    Card,
    CardAppOwnership,
    CardAppResourceSelection,
    Project,
    ProjectColumn,
    ProjectRole,
    User,
    WorkflowStageDefinition,
)
from .AppConnectionAuthentication import authenticate_connection_credential
from .AppGovernance import AppGovernanceDenied, _current, require_connection_access
from .CardApprovalGate import pending_card_approvals
from .DomainService import DomainService


class AppExecutionCredentialDenied(AppGovernanceDenied):
    """Invalid app identity, distinct from an authenticated scope denial."""


def evaluate_current_execution_grant(token: str, project_id: int, card_id: int, expected_generation: int) -> dict:
    """Evaluate current authority. This is not a persisted lease or a start receipt."""
    if type(expected_generation) is not int or expected_generation < 1:
        raise ValueError("Execution generation must be positive")
    with DbSession.atomic() as db:
        try:
            principal = authenticate_connection_credential(token)
        except AppGovernanceDenied as exc:
            raise AppExecutionCredentialDenied() from exc
        return _evaluate_principal(db, principal, project_id, card_id, expected_generation)


def evaluate_connection_execution_grant(connection_id, project_id, card_id, expected_generation):
    """Internal outbox fence; derives identity from current connection, never event content."""
    from .AppConnectionAuthentication import AuthenticatedAppConnection, _connection

    with DbSession.atomic() as db:
        connection = _connection(db, connection_id)
        principal = AuthenticatedAppConnection(
            app_key=connection.app_key,
            connection_id=connection.id,
            credential_id=0,
            owner_id=connection.owner_id,
            organization_id=connection.organization_id,
        )
        return _evaluate_principal(db, principal, project_id, card_id, expected_generation)


def _evaluate_principal(db, principal, project_id, card_id, expected_generation):
    project = _current(db, Project, project_id)
    card = _current(db, Card, card_id)
    connection = _current(db, AppConnection, principal.connection_id)
    actor = _current(db, User, principal.owner_id)
    if (
        any(value is None for value in (connection, project, card, actor))
        or card.project_id != project.id
        or card.deleted_at
        or card.archived_at
        or card.source_type
    ):
        raise AppGovernanceDenied()
    require_connection_access(db, actor, project, connection, unattended=True)
    role = db.exec(
        SqlBuilder.select.table(ProjectRole).where(
            ProjectRole.project_id == project.id, ProjectRole.user_id == actor.id
        )
    ).first()
    if project.owner_id != actor.id and (role is None or not role.is_granted("card_update")):
        raise AppGovernanceDenied()
    # API automation cannot read private cards; internal classification uses the
    # existing instance policy rather than company-specific identity facts.
    if card.visibility not in ("SHARED", "INTERNAL") or (
        card.visibility == "INTERNAL" and not DomainService().card._resolve_internal_access(actor)
    ):
        raise AppGovernanceDenied()
    owner = db.exec(
        SqlBuilder.select.table(CardAppOwnership).where(CardAppOwnership.card_id == card.id).with_for_update()
    ).first()
    if owner is None or owner.app_key != principal.app_key:
        raise AppGovernanceDenied()
    selection = db.exec(
        SqlBuilder.select.table(CardAppResourceSelection)
        .where(
            CardAppResourceSelection.card_id == card.id,
            CardAppResourceSelection.app_key == principal.app_key,
        )
        .with_for_update()
    ).first()
    if selection is None or not selection.resource_uids or selection.connection_id != connection.id:
        raise AppGovernanceDenied()
    definition = db.exec(
        SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == principal.app_key).with_for_update()
    ).first()
    # Execution is offered only by approved external definitions. Built-in
    # signal adapters do not acquire it through implicit fallback.
    declared = definition.declaration if definition else {}
    binding = db.exec(
        SqlBuilder.select.table(BoardAppBinding)
        .where(
            BoardAppBinding.project_id == project.id,
            BoardAppBinding.app_key == principal.app_key,
        )
        .with_for_update()
    ).first()
    if (
        not definition
        or not definition.is_enabled
        or not binding
        or binding.state != "enabled"
        or not {"resources.read", "execution.run"}.issubset(declared.get("capabilities", []))
        or not {"resources.read", "execution.run"}.issubset(binding.granted_capabilities)
    ):
        raise AppGovernanceDenied()
    resources = db.exec(
        SqlBuilder.select.table(AppResourceBinding)
        .where(
            AppResourceBinding.id.in_([SnowflakeID.from_short_code(uid) for uid in selection.resource_uids]),
            AppResourceBinding.board_binding_id == binding.id,
            AppResourceBinding.connection_id == connection.id,
            AppResourceBinding.is_selected == True,  # noqa: E712
            AppResourceBinding.access_state == "granted",
            AppResourceBinding.resource_type.in_(declared.get("resource_types", [])),
        )
        .with_for_update()
    ).all()
    if sorted(r.get_uid() for r in resources) != sorted(selection.resource_uids):
        raise AppGovernanceDenied()
    column = db.exec(SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.id == card.project_column_id)).first()
    stage = db.exec(
        SqlBuilder.select.table(WorkflowStageDefinition).where(WorkflowStageDefinition.key == "ready")
    ).first()
    if (
        column is None
        or column.is_archive
        or column.deleted_at
        or column.project_id != project.id
        or column.workflow_stage != "ready"
        or stage is None
        or not stage.is_active
        or not stage.is_builtin
        or not binding.stage_transitions_enabled
        or binding.workflow_mapping.get("ready") != column.get_uid()
    ):
        raise AppGovernanceDenied()
    blockers = db.exec(
        select(text("1"))
        .select_from(text("card c JOIN card_relationship r ON r.card_id_child = c.id " + BLOCKING_RELATION_JOINS))
        .where(text("c.id = :card_id"))
        .where(text(UNSATISFIED_PREREQUISITE)),
        params={"card_id": int(card.id)},
    ).first()
    if blockers:
        raise AppGovernanceDenied()
    if pending_card_approvals([card.id]).get(card.id, 0):
        raise AppGovernanceDenied()
    generation = db.exec(
        select(text("COALESCE((SELECT execution_generation FROM card_execution_generation WHERE card_id=:card_id),0)")),
        params={"card_id": int(card.id)},
    ).first()
    actual_generation = int(generation[0] if hasattr(generation, "__getitem__") else generation)
    if actual_generation != expected_generation:
        raise AppGovernanceDenied()
    authority = {
        "schema_version": 1,
        "card_uid": card.get_uid(),
        "app_key": principal.app_key,
        "connection_uid": connection.get_uid(),
        "generation": actual_generation,
        "resource_uids": sorted(selection.resource_uids),
        "resource_revisions": {resource.get_uid(): resource.access_revision for resource in resources},
        "card_revision": card.last_change_seq,
        "ownership_revision": owner.revision,
        "selection_revision": selection.revision,
        "binding_revision": binding.edit_revision(),
    }
    authority["authority_version"] = sha256(
        dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return authority
