"""Bounded board Signal discovery; hidden card links never affect visible results."""

import re
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    AppSignal,
    BoardAppBinding,
    Card,
    CardAppSignalBinding,
    Project,
    User,
)
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.AppSignalProjection import (
    authorized_signal_rows,
    provider_resource_condition,
    signal_resource_name,
    supported_signal_condition,
)
from langboard_shared.domain.services.CardVisibilityPolicy import card_visibility_scope
from langboard_shared.helpers import InfraHelper
from sqlalchemy import and_, func, select
from .GitHubManifest import GitHubManifestUnavailable


_resource_name = signal_resource_name


def list_board_signals(service, actor, project_uid, after=None):
    if service.workflow_stage._authorized_app_board(actor, project_uid, ProjectRoleAction.Read) is None:
        raise GitHubManifestUnavailable()
    resolved = service.card.resolve_visibility_context(project_uid, actor)
    if resolved is None or not resolved[1].project_member:
        raise GitHubManifestUnavailable()
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid inbox cursor")
    project, context = resolved
    supported_occurrence = supported_signal_condition()
    eligibility = provider_resource_condition()
    # GitHub checks are per commit; Dokploy deployments have their own external identity.
    identity = (AppSignal.provider, AppSignal.resource_id, AppSignal.external_id, AppSignal.commit_sha)
    latest = (
        select(
            AppSignal.provider,
            AppSignal.resource_id,
            AppSignal.external_id,
            AppSignal.commit_sha,
            func.max(AppSignal.occurred_at).label("occurred_at"),
        )
        .join(AppResourceBinding, AppResourceBinding.id == AppSignal.resource_id)
        .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
        .where(
            BoardAppBinding.project_id == project.id,
            supported_occurrence,
        )
        .group_by(*identity)
        .subquery()
    )
    occurrences = (
        select(
            func.max(AppSignal.id).label("signal_id"),
            func.min(AppSignal.outcome).label("minimum"),
            func.max(AppSignal.outcome).label("maximum"),
        )
        .join(
            latest,
            and_(
                AppSignal.provider == latest.c.provider,
                AppSignal.resource_id == latest.c.resource_id,
                AppSignal.external_id == latest.c.external_id,
                AppSignal.commit_sha == latest.c.commit_sha,
                AppSignal.occurred_at == latest.c.occurred_at,
            ),
        )
        .where(supported_occurrence)
        .group_by(*identity)
        .subquery()
    )
    linked = (
        select(CardAppSignalBinding.id)
        .join(Card, Card.id == CardAppSignalBinding.card_id)
        .where(
            Card.project_id == project.id,
            Card.deleted_at.is_(None),
            card_visibility_scope(context),
            CardAppSignalBinding.is_enabled == True,  # noqa: E712
            CardAppSignalBinding.resource_id == AppSignal.resource_id,
            CardAppSignalBinding.external_id == AppSignal.external_id,
            CardAppSignalBinding.commit_sha == AppSignal.commit_sha,
        )
        .correlate(AppSignal)
        .exists()
    )
    query = (
        select(AppSignal, AppResourceBinding, AppConnection, occurrences.c.minimum, occurrences.c.maximum)
        .join(occurrences, occurrences.c.signal_id == AppSignal.id)
        .join(AppResourceBinding, AppResourceBinding.id == AppSignal.resource_id)
        .join(BoardAppBinding, BoardAppBinding.id == AppResourceBinding.board_binding_id)
        .join(Project, Project.id == BoardAppBinding.project_id)
        .join(AppConnection, AppConnection.id == AppResourceBinding.connection_id)
        .join(User, User.id == AppConnection.owner_id)
        .where(Project.id == project.id, eligibility, AppSignal.provider == AppConnection.app_key, ~linked)
    )
    with DbSession.use(readonly=False) as db:
        if after is not None:
            cursor_id = InfraHelper.convert_id(after)
            if db.exec(query.where(AppSignal.id == cursor_id).limit(1)).first() is None:
                raise ValueError("Invalid inbox cursor")
            query = query.where(AppSignal.id < cursor_id)
        rows = db.exec(query.order_by(AppSignal.id.desc()).limit(26)).all()
        allowed = {
            row.id
            for row in authorized_signal_rows(
                db, [(resource, connection, None) for _, resource, connection, _, _ in rows[:25]]
            )
        }
        return {
            "items": [
                {
                    "signal_uid": signal.get_uid(),
                    "provider": signal.provider,
                    "event_type": signal.event_type,
                    "resource_uid": resource.get_uid(),
                    "resource_type": resource.resource_type,
                    "resource_name": _resource_name(resource),
                    "connection_uid": connection.get_uid(),
                    "external_id": signal.external_id,
                    "commit_sha": signal.commit_sha,
                    "occurred_at": signal.occurred_at,
                    "outcome": minimum if minimum == maximum else None,
                    "conflict": minimum != maximum,
                    "can_bind_card": signal.provider in {"github", "dokploy"},
                }
                for signal, resource, connection, minimum, maximum in rows[:25]
                if resource.id in allowed
            ],
            "next_cursor": rows[24][0].get_uid() if len(rows) > 25 else None,
        }
