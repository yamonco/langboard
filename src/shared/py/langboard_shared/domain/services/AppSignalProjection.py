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


def card_signal_projections(cards):
    """Caller supplies its authorized card batch; current consumer authority is checked on primary."""
    if not cards:
        return {}
    card_ids = [card.id for card in cards]
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
    with DbSession.use(readonly=False) as db:
        rows = db.exec(
            select(CardAppSignalBinding, AppConnection, Card.last_change_seq)
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
                Project.deleted_at.is_(None),
                BoardAppBinding.project_id == Card.project_id,
                BoardAppBinding.app_key == "github",
                BoardAppBinding.state.in_(["enabled", "needs_attention"]),
                cast(BoardAppBinding.granted_capabilities, Text).contains('"signals.read"'),
                AppConnection.app_key == "github",
                AppConnection.state == "connected",
                User.deleted_at.is_(None),
                User.activated_at.is_not(None),
                or_(User.is_admin == True, Project.owner_id == User.id, and_(membership, update_grant)),  # noqa: E712
                AppResourceBinding.resource_type == "repository",
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.access_state == "granted",
                CardAppSignalBinding.is_enabled == True,  # noqa: E712
            )
        ).all()
        if not rows:
            return {}
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
            return {}
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
        if not eligible:
            return {}
        matching = and_(
            AppSignal.resource_id == CardAppSignalBinding.resource_id,
            AppSignal.event_type == "check.completed",
            AppSignal.provider == "github",
            AppSignal.external_id == CardAppSignalBinding.external_id,
            AppSignal.commit_sha == CardAppSignalBinding.commit_sha,
        )
        latest = (
            select(CardAppSignalBinding.id.label("binding_id"), func.max(AppSignal.occurred_at).label("occurred_at"))
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
            )
            .join(latest, latest.c.binding_id == CardAppSignalBinding.id)
            .join(
                AppSignal,
                and_(matching, AppSignal.occurred_at == latest.c.occurred_at),
            )
            .group_by(CardAppSignalBinding.id, latest.c.occurred_at)
        ).all()
    by_binding = {row[0]: row for row in evidence}
    current_revisions = {binding.card_id: revision for binding, _, revision in rows}
    result = {}
    for binding in eligible:
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
                else "unknown"
            )
        result.setdefault(binding.card_id, []).append(
            {
                "binding_uid": binding.get_uid(),
                "provider": "github",
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
