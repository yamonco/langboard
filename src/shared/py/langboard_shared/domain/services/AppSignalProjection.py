"""Occurrence-ordered provider evidence for explicit card scopes; never reviewer approval."""

import re
from sqlalchemy import Text, and_, cast, func, or_, select, tuple_
from ...core.db import DbSession
from ...helpers import InfraHelper
from ..models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    Card,
    CardAppSignalBinding,
    Organization,
    Project,
    ProjectAssignedUser,
    ProjectRole,
    SecretReference,
    User,
)


def signal_resource_conditions(*, app_key="github", resource_type="repository", capability="signals.read"):
    """Current owner consumption authority, shared by evidence and resource discovery."""
    membership = (
        select(ProjectAssignedUser.id)
        .where(
            ProjectAssignedUser.project_id == Project.id,
            ProjectAssignedUser.user_id == User.id,
        )
        .exists()
    )
    actions = "," + cast(ProjectRole.actions, Text) + ","
    update_grant = (
        select(ProjectRole.id)
        .where(
            ProjectRole.project_id == Project.id,
            ProjectRole.user_id == User.id,
            or_(actions.contains(",*,"), actions.contains(",update,")),
        )
        .exists()
    )
    return (
        Project.deleted_at.is_(None),
        BoardAppBinding.app_key == app_key,
        BoardAppBinding.state.in_(["enabled", "needs_attention"]),
        cast(BoardAppBinding.granted_capabilities, Text).contains(f'"{capability}"'),
        AppConnection.app_key == BoardAppBinding.app_key,
        AppConnection.state == "connected",
        User.deleted_at.is_(None),
        User.activated_at.is_not(None),
        or_(User.is_admin == True, Project.owner_id == User.id, and_(membership, update_grant)),  # noqa: E712
        AppResourceBinding.resource_type == resource_type,
        AppResourceBinding.is_selected == True,  # noqa: E712
        AppResourceBinding.access_state == "granted",
    )


DOKPLOY_EVENTS = (
    "deployment.queued",
    "deployment.started",
    "deployment.succeeded",
    "deployment.failed",
    "deployment.cancelled",
)


def supported_signal_condition():
    return or_(
        and_(AppSignal.provider == "github", AppSignal.event_type == "check.completed"),
        and_(AppSignal.provider == "dokploy", AppSignal.event_type.in_(DOKPLOY_EVENTS), AppSignal.commit_sha == ""),
    )


def provider_resource_condition():
    from .AppManifest import APP_MANIFESTS

    return or_(
        and_(*signal_resource_conditions()),
        or_(
            *(
                and_(
                    *signal_resource_conditions(app_key="dokploy", resource_type=kind),
                    cast(BoardAppBinding.granted_capabilities, Text).contains('"deployments.read"'),
                )
                for kind in APP_MANIFESTS["dokploy"].resource_types
                if kind in {"application", "compose"}
            )
        ),
    )


def signal_resource_name(resource):
    path = resource.resource_path
    leaf = path[-1] if isinstance(path, list) and path else None
    name = leaf.get("name") if isinstance(leaf, dict) else None
    return (name if isinstance(name, str) and name.strip() else resource.external_resource_id)[:200]


def authorized_signal_rows(db, rows):
    """Rows contain a scope/resource, connection and opaque third field. No secret values."""
    actions = "," + cast(ProjectRole.actions, Text) + ","
    # Canonical references only; one bounded batch lookup, never resolve secret material.
    reference_ids = {}
    for binding, connection, _ in rows:
        uri = connection.credential_reference or ""
        if re.fullmatch(r"secret://ref/[A-Za-z0-9]{1,11}", uri):
            try:
                reference_ids[binding.id] = InfraHelper.convert_id(uri.removeprefix("secret://ref/"))
            except (ValueError, TypeError):
                continue
    if not reference_ids:
        return []
    # Match the native SecretReference scope rules without per-card authority reads.
    scope_member = (
        select(ProjectAssignedUser.id)
        .where(
            ProjectAssignedUser.project_id == Project.id,
            ProjectAssignedUser.user_id == AppConnection.owner_id,
        )
        .correlate(Project, AppConnection)
        .exists()
    )
    scope_update = (
        select(ProjectRole.id)
        .where(
            ProjectRole.project_id == Project.id,
            ProjectRole.user_id == AppConnection.owner_id,
            or_(actions.contains(",*,"), actions.contains(",update,")),
        )
        .correlate(Project, AppConnection)
        .exists()
    )
    project_scope = (
        select(Project.id)
        .where(
            Project.id == SecretReference.scope_id,
            Project.deleted_at.is_(None),
            or_(
                User.is_admin == True,  # noqa: E712
                Project.owner_id == AppConnection.owner_id,  # noqa: E712
                and_(scope_member, scope_update),
            ),
        )
        .correlate(SecretReference, AppConnection, User)
        .exists()
    )
    workspace_scope = (
        select(Organization.id)
        .where(
            Organization.id == SecretReference.scope_id,
            Organization.is_active == True,  # noqa: E712
            Organization.suspended_at.is_(None),
            Organization.owner_user_id == AppConnection.owner_id,
        )
        .correlate(SecretReference, AppConnection)
        .exists()
    )
    pairs = {
        (reference_ids[binding.id], connection.id) for binding, connection, _ in rows if binding.id in reference_ids
    }
    authorized = set(
        db.exec(
            select(SecretReference.id, AppConnection.id)
            .join(
                AppConnection,
                tuple_(SecretReference.id, AppConnection.id).in_(pairs),
            )
            .join(User, User.id == AppConnection.owner_id)
            .where(
                SecretReference.state == "active",
                or_(
                    and_(SecretReference.scope == "personal", SecretReference.scope_id == AppConnection.owner_id),
                    and_(SecretReference.scope == "project", project_scope),
                    and_(SecretReference.scope == "workspace", workspace_scope),
                ),
            )
        ).all()
    )
    eligible = [
        binding for binding, connection, _ in rows if (reference_ids.get(binding.id), connection.id) in authorized
    ]
    return eligible


def card_signal_projections(cards):
    """Caller supplies its authorized card batch; current consumer authority is checked on primary."""
    if not cards:
        return {}
    card_ids = [card.id for card in cards]
    with DbSession.use(readonly=False) as db:
        rows = db.exec(
            select(CardAppSignalBinding, AppConnection, Card.last_change_seq, AppResourceBinding)
            .join(
                AppResourceBinding,
                AppResourceBinding.id == CardAppSignalBinding.resource_id,
            )
            .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
            .join(
                Card,
                Card.id == CardAppSignalBinding.card_id,
            )
            .join(Project, Project.id == Card.project_id)
            .join(AppConnection, AppConnection.id == AppResourceBinding.connection_id)
            .join(
                User,
                User.id == AppConnection.owner_id,
            )
            .where(
                Card.id.in_(card_ids),
                Card.deleted_at.is_(None),
                provider_resource_condition(),
                BoardAppBinding.project_id == Card.project_id,
                CardAppSignalBinding.is_enabled == True,  # noqa: E712
            )
        ).all()
        if not rows:
            return {}
        eligible = authorized_signal_rows(
            db, [(binding, connection, revision) for binding, connection, revision, _ in rows]
        )
        if not eligible:
            return {}
        matching = and_(
            AppSignal.resource_id == CardAppSignalBinding.resource_id,
            supported_signal_condition(),
            AppSignal.provider == AppConnection.app_key,
            AppSignal.external_id == CardAppSignalBinding.external_id,
            AppSignal.commit_sha == CardAppSignalBinding.commit_sha,
        )
        latest = (
            select(CardAppSignalBinding.id.label("binding_id"), func.max(AppSignal.occurred_at).label("occurred_at"))
            .join(AppResourceBinding, AppResourceBinding.id == CardAppSignalBinding.resource_id)
            .join(AppConnection, AppConnection.id == AppResourceBinding.connection_id)
            .join(
                AppSignal,
                matching,
            )
            .where(CardAppSignalBinding.id.in_([binding.id for binding in eligible]))
            .group_by(CardAppSignalBinding.id)
            .subquery()
        )
        evidence = db.exec(
            select(
                CardAppSignalBinding.id,
                func.min(AppSignal.outcome),
                func.max(AppSignal.outcome),
                func.max(AppSignal.id),
                latest.c.occurred_at,
                func.max(AppSignal.event_type),
            )
            .join(AppResourceBinding, AppResourceBinding.id == CardAppSignalBinding.resource_id)
            .join(AppConnection, AppConnection.id == AppResourceBinding.connection_id)
            .join(latest, latest.c.binding_id == CardAppSignalBinding.id)
            .join(
                AppSignal,
                and_(matching, AppSignal.occurred_at == latest.c.occurred_at),
            )
            .group_by(CardAppSignalBinding.id, latest.c.occurred_at)
        ).all()
    by_binding = {row[0]: row for row in evidence}
    current_revisions = {binding.card_id: revision for binding, _, revision, _ in rows}
    resources = {binding.id: (connection.app_key, resource) for binding, connection, _, resource in rows}
    result = {}
    for binding in eligible:
        provider, resource = resources[binding.id]
        proof = by_binding.get(binding.id)
        state = "stale" if binding.source_change_seq != current_revisions[binding.card_id] else "unavailable"
        outcome = None
        if state != "stale" and proof:
            outcome = proof[1] if proof[1] == proof[2] else None
            state = (
                "conflict"
                if proof[1] != proof[2]
                else "passed"
                if outcome == "success"
                else "failed"
                if outcome in {"failure", "timed_out"}
                else outcome
                if provider == "dokploy" and outcome in {"queued", "running", "cancelled"}
                else "unknown"
            )
        result.setdefault(binding.card_id, []).append(
            {
                "binding_uid": binding.get_uid(),
                "provider": provider,
                "event_type": proof[5] if proof and proof[1] == proof[2] else None,
                "resource_type": resource.resource_type,
                "resource_name": signal_resource_name(resource),
                "resource_uid": InfraHelper.convert_uid(binding.resource_id),
                "external_id": binding.external_id,
                "commit_sha": binding.commit_sha,
                "source_change_seq": binding.source_change_seq,
                "revision": binding.revision,
                "state": state,
                "outcome": outcome,
                "signal_uid": InfraHelper.convert_uid(proof[3]) if proof else None,
                "occurred_at": proof[4] if proof else None,
            }
        )
    return result
