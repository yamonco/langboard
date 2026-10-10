"""Explicit board administrator ownership decisions with durable audit evidence."""

from sqlalchemy import update
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ..models import (
    AppDefinition,
    Card,
    CardAppOwnership,
    CardAppOwnershipAudit,
    Project,
    ProjectAssignedUser,
    ProjectRole,
    User,
)
from .AppGovernance import AppGovernanceDenied, _current, require_current_project_policy
from .AppManifest import APP_MANIFESTS


class CardAppOwnershipConflict(Exception):
    pass


def _admin_card(db, actor, project_id, card_id):
    current = _current(db, User, actor.id)
    project = _current(db, Project, project_id)
    card = _current(db, Card, card_id)
    if (
        current is None
        or current.deleted_at
        or not current.activated_at
        or project is None
        or project.deleted_at
        or card is None
        or card.deleted_at
        or card.project_id != project.id
    ):
        raise AppGovernanceDenied()
    if not current.is_admin and project.owner_id != current.id:
        member = db.exec(
            SqlBuilder.select.table(ProjectAssignedUser).where(
                ProjectAssignedUser.project_id == project.id,
                ProjectAssignedUser.user_id == current.id,
            )
        ).first()
        role = db.exec(
            SqlBuilder.select.table(ProjectRole).where(
                ProjectRole.project_id == project.id,
                ProjectRole.user_id == current.id,
            )
        ).first()
        if member is None or role is None or not role.is_granted("update"):
            raise AppGovernanceDenied()
    # An administrator cannot use app governance to discover another user's private card.
    if card.visibility == "PRIVATE" and card.owner_user_id != current.id:
        raise AppGovernanceDenied()
    return current, project, card


def set_card_app_ownership(actor, project_id, card_id, app_key, expected_revision):
    """Configuration boundary; not exposed until canonical mutation fences are wired."""
    if app_key is not None and (not isinstance(app_key, str) or not app_key or len(app_key) > 32):
        raise ValueError("Invalid app ownership key")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
        raise ValueError("Invalid ownership revision")
    with DbSession.atomic() as db:
        current, project, card = _admin_card(db, actor, project_id, card_id)
        if app_key is not None:
            require_current_project_policy(db, project)
            definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == app_key)).first()
            if (definition is not None and not definition.is_enabled) or (
                definition is None and app_key not in APP_MANIFESTS
            ):
                raise AppGovernanceDenied()
        row = db.exec(SqlBuilder.select.table(CardAppOwnership).where(CardAppOwnership.card_id == card.id)).first()
        if (row is None and expected_revision is not None) or (row is not None and expected_revision != row.revision):
            raise CardAppOwnershipConflict()
        previous = row.app_key if row else None
        if row is not None and previous == app_key:
            return {"app_key": row.app_key, "revision": row.revision, "changed": False}
        if row is None:
            if app_key is None:
                return {"app_key": None, "revision": None, "changed": False}
            row = CardAppOwnership(card_id=card.id, app_key=app_key)
            db.insert(row)
        else:
            revision = row.revision + 1
            changed = db.exec(
                update(CardAppOwnership)
                .where(
                    CardAppOwnership.id == row.id,
                    CardAppOwnership.revision == expected_revision,
                )
                .values(app_key=app_key, revision=revision, updated_at=SafeDateTime.now())
            )
            if changed != 1:
                raise CardAppOwnershipConflict()
            row.app_key, row.revision = app_key, revision
        db.insert(
            CardAppOwnershipAudit(
                card_id=card.id, actor_id=current.id, previous_app_key=previous, app_key=app_key, revision=row.revision
            )
        )
        return {"app_key": row.app_key, "revision": row.revision, "changed": True}
