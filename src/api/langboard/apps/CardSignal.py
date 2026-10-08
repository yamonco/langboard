"""User-selected card check scope; visibility and revision fencing precede mutation."""

from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppSignal, Card, CardAppSignalBinding
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.AppSignalProjection import card_signal_projections
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibility
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.helpers import InfraHelper
from sqlalchemy import func, select
from .GitHubManifest import GitHubManifestUnavailable
from .GitHubSignal import _scope


class CardSignalConflict(Exception):
    pass


def authorized_card(service, actor, project_uid, card_uid):
    if (
        service.workflow_stage._authorized_app_board(actor, project_uid, ProjectRoleAction.CardUpdate, lock=True)
        is None
    ):
        raise GitHubManifestUnavailable()
    resolved = service.card.resolve_readable_card(project_uid, card_uid, actor)
    if resolved is None:
        raise GitHubManifestUnavailable()
    with DbSession.use(readonly=False) as db:
        card = db.exec(
            SqlBuilder.select.table(Card).where(Card.id == resolved[1].id, Card.deleted_at.is_(None)).with_for_update()
        ).first()
    if card is None or not resolved[2].can_read_card(CardVisibility(card.visibility), owner_user_id=card.owner_user_id):
        raise GitHubManifestUnavailable()
    return card


def bind_check(
    service,
    actor,
    project_uid,
    card_uid,
    connection_uid,
    resource_uid,
    signal_uid,
    source_change_seq,
    expected_revision,
):
    with DbSession.atomic() as db:
        card = authorized_card(service, actor, project_uid, card_uid)
        if card.last_change_seq != source_change_seq:
            raise CardSignalConflict()
        owner, connection, resource = _scope(service, db, project_uid, connection_uid, resource_uid, actor, lock=True)
        try:
            meta = service.secret_reference._find(owner, connection.credential_reference, lock=True).metadata()
        except SecretReferenceUnavailable:
            raise GitHubManifestUnavailable() from None
        if meta["state"] != "active":
            raise GitHubManifestUnavailable()
        signal = db.exec(
            SqlBuilder.select.table(AppSignal).where(
                AppSignal.id == InfraHelper.convert_id(signal_uid),
                AppSignal.resource_id == resource.id,
                AppSignal.provider == "github",
                AppSignal.event_type == "check.completed",
            )
        ).first()
        if signal is None or not signal.commit_sha or not signal.external_id:
            raise GitHubManifestUnavailable()
        binding = db.exec(
            SqlBuilder.select.table(CardAppSignalBinding)
            .where(
                CardAppSignalBinding.card_id == card.id,
                CardAppSignalBinding.resource_id == resource.id,
                CardAppSignalBinding.external_id == signal.external_id,
                CardAppSignalBinding.commit_sha == signal.commit_sha,
            )
            .with_for_update()
        ).first()
        if binding is None or not binding.is_enabled:
            count = db.exec(
                select(func.count())
                .select_from(CardAppSignalBinding)
                .where(
                    CardAppSignalBinding.card_id == card.id,
                    CardAppSignalBinding.is_enabled == True,  # noqa: E712
                )
            ).first()[0]
            if count >= 25:
                raise CardSignalConflict()
        if binding is None:
            if expected_revision is not None:
                raise CardSignalConflict()
            binding = CardAppSignalBinding(
                card_id=card.id,
                resource_id=resource.id,
                external_id=signal.external_id,
                commit_sha=signal.commit_sha,
                source_change_seq=source_change_seq,
            )
            db.insert(binding)
        else:
            if expected_revision != binding.revision:
                raise CardSignalConflict()
            binding.source_change_seq = source_change_seq
            binding.is_enabled = True
            binding.revision += 1
            db.update(binding)
        return {"binding_uid": binding.get_uid(), "revision": binding.revision}


def unlink_check(service, actor, project_uid, card_uid, binding_uid, expected_revision):
    with DbSession.atomic() as db:
        card = authorized_card(service, actor, project_uid, card_uid)
        binding = db.exec(
            SqlBuilder.select.table(CardAppSignalBinding)
            .where(
                CardAppSignalBinding.id == InfraHelper.convert_id(binding_uid),
                CardAppSignalBinding.card_id == card.id,
            )
            .with_for_update()
        ).first()
        if binding is None:
            raise GitHubManifestUnavailable()
        if binding.revision != expected_revision:
            raise CardSignalConflict()
        binding.is_enabled = False
        binding.revision += 1
        db.update(binding)
        return {"binding_uid": binding.get_uid(), "revision": binding.revision, "is_enabled": False}


def read_checks(service, actor, project_uid, card_uid):
    if service.workflow_stage._authorized_app_board(actor, project_uid, ProjectRoleAction.Read) is None:
        raise GitHubManifestUnavailable()
    resolved = service.card.resolve_readable_card(project_uid, card_uid, actor)
    if resolved is None:
        raise GitHubManifestUnavailable()
    card = resolved[1]
    with DbSession.use(readonly=False) as db:
        bindings = db.exec(
            SqlBuilder.select.table(CardAppSignalBinding)
            .where(
                CardAppSignalBinding.card_id == card.id,
                CardAppSignalBinding.is_enabled == True,  # noqa: E712
            )
            .order_by(CardAppSignalBinding.id)
            .limit(25)
        ).all()
    return {
        "items": card_signal_projections([card]).get(card.id, []),
        "bindings": [{"binding_uid": binding.get_uid(), "revision": binding.revision} for binding in bindings],
        "source_change_seq": card.last_change_seq,
    }


def list_card_resources(service, actor, project_uid, card_uid, after=None):
    """Read-visible, currently consumable selected repositories; bounded discovery, no provider calls."""
    import re
    from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding, Project, User
    from langboard_shared.domain.services.AppSignalProjection import authorized_signal_rows, signal_resource_conditions

    if service.workflow_stage._authorized_app_board(actor, project_uid, ProjectRoleAction.Read) is None:
        raise GitHubManifestUnavailable()
    resolved = service.card.resolve_readable_card(project_uid, card_uid, actor)
    if resolved is None:
        raise GitHubManifestUnavailable()
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid resource cursor")
    with DbSession.use(readonly=False) as db:
        statement = (
            select(AppResourceBinding, AppConnection, AppResourceBinding.id)
            .join(
                BoardAppBinding,
                BoardAppBinding.id == AppResourceBinding.board_binding_id,
            )
            .join(Project, Project.id == BoardAppBinding.project_id)
            .join(
                AppConnection,
                AppConnection.id == AppResourceBinding.connection_id,
            )
            .join(User, User.id == AppConnection.owner_id)
            .where(
                Project.id == resolved[0].id,
                *signal_resource_conditions(),
            )
        )
        if after is not None:
            statement = statement.where(AppResourceBinding.id > InfraHelper.convert_id(after))
        rows = db.exec(statement.order_by(AppResourceBinding.id).limit(26)).all()
        allowed = authorized_signal_rows(db, rows[:25]) if rows else []
        return {
            "items": [
                {
                    "uid": resource.get_uid(),
                    "connection_uid": InfraHelper.convert_uid(resource.connection_id),
                    "name": resource.resource_path[-1].get("name", resource.external_resource_id)
                    if resource.resource_path
                    else resource.external_resource_id,
                }
                for resource in allowed
            ],
            "next_cursor": rows[24][0].get_uid() if len(rows) > 25 else None,
        }
