"""Current app policy and connection ownership checks at native service boundaries."""

import hashlib
import json
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ...publishers import AppSettingPublisher
from ..models import AppConnection, AppGovernancePolicy, Organization, Project, ProjectAssignedUser, User


MODES = ("disabled", "approved_only", "personal_allowed")


class AppGovernanceDenied(Exception):
    pass


class AppGovernanceConflict(Exception):
    pass


def _current(db, model, identifier, *, for_update=True):
    statement = SqlBuilder.select.table(model).where(model.id == identifier)
    if for_update:
        statement = statement.with_for_update()
    return db.exec(statement).first()


def _actor(db, actor):
    current = _current(db, User, actor.id)
    if current is None or current.deleted_at or not current.activated_at:
        raise AppGovernanceDenied()
    return current


def _organization(db, organization_id, *, for_update=True):
    organization = _current(db, Organization, organization_id, for_update=for_update)
    if organization is None or not organization.is_active or organization.suspended_at:
        raise AppGovernanceDenied()
    return organization


def _authorize(db, actor, organization_id):
    actor = _actor(db, actor)
    if organization_id is None:
        if not actor.is_admin:
            raise AppGovernanceDenied()
    else:
        organization = _organization(db, organization_id)
        if not actor.is_admin and organization.owner_user_id != actor.id:
            raise AppGovernanceDenied()


def _key(organization_id):
    return "global" if organization_id is None else f"organization:{int(organization_id)}"


def _row(db, organization_id, *, for_update=True):
    statement = SqlBuilder.select.table(AppGovernancePolicy).where(
        AppGovernancePolicy.scope_key == _key(organization_id)
    )
    if for_update:
        statement = statement.with_for_update()
    return db.exec(statement).first()


def _revision(key, mode, generation, ceiling=None):
    value = json.dumps([key, mode, generation, ceiling], separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def current_policy(db, organization_id=None, *, for_update=False):
    """Read at most two indexed rows. Organization absence inherits instance policy."""
    global_row = _row(db, None, for_update=for_update)
    global_mode = global_row.mode if global_row else "approved_only"
    global_revision = _revision("global", global_mode, global_row.generation if global_row else 0)
    if organization_id is None:
        return {"mode": global_mode, "effective_mode": global_mode, "revision": global_revision}
    _organization(db, organization_id, for_update=for_update)
    row = _row(db, organization_id, for_update=for_update)
    mode = row.mode if row else None
    effective = min((global_mode, mode or global_mode), key=MODES.index)
    return {
        "mode": mode,
        "effective_mode": effective,
        "revision": _revision(_key(organization_id), mode, row.generation if row else 0, global_revision),
    }


def get_policy(actor, organization_id=None):
    with DbSession.atomic() as db:
        _authorize(db, actor, organization_id)
        return current_policy(db, organization_id, for_update=True)


def save_policy(actor, mode, expected_revision, organization_id=None):
    if mode not in MODES and not (mode is None and organization_id is not None):
        raise ValueError("Invalid app governance mode")
    try:
        with DbSession.atomic() as db:
            _authorize(db, actor, organization_id)
            policy = current_policy(db, organization_id, for_update=True)
            if expected_revision != policy["revision"]:
                raise AppGovernanceConflict()
            row = _row(db, organization_id)
            if row is None:
                db.insert(
                    AppGovernancePolicy(scope_key=_key(organization_id), organization_id=organization_id, mode=mode)
                )
            else:
                count = db.exec(
                    update(AppGovernancePolicy)
                    .where(AppGovernancePolicy.id == row.id, AppGovernancePolicy.generation == row.generation)
                    .values(mode=mode, generation=row.generation + 1, updated_at=SafeDateTime.now())
                )
                if count != 1:
                    raise AppGovernanceConflict()
            result = current_policy(db, organization_id, for_update=True)
            db.after_commit(AppSettingPublisher.apps_changed)
            return result
    except IntegrityError as exc:
        raise AppGovernanceConflict() from exc


def require_app_allowed(db, project, *, approved=True, personal=False):
    """Policy gate for callers that already enforce their own project authority."""
    current = _current(db, Project, project.id, for_update=False)
    if current is None or current.deleted_at:
        raise AppGovernanceDenied()
    return require_current_project_policy(db, current, approved=approved, personal=personal)


def require_current_project_policy(db, current, *, approved=True, personal=False):
    """Policy gate for a project freshly read from the primary in this transaction."""
    if current.deleted_at:
        raise AppGovernanceDenied()
    policy = current_policy(db, current.organization_id)
    mode = policy["effective_mode"]
    if mode == "disabled" or ((personal or not approved) and mode != "personal_allowed"):
        raise AppGovernanceDenied()
    return policy


def require_connection_access(db, actor, project, connection, *, unattended=False, approved=True, personal_app=False):
    """Return only an authorized current connection; never expose another person's account."""
    actor = _actor(db, actor)
    project = _current(db, Project, project.id)
    connection = _current(db, AppConnection, connection.id)
    if project is None or project.deleted_at or connection is None or connection.state != "connected":
        raise AppGovernanceDenied()
    member = db.exec(
        SqlBuilder.select.table(ProjectAssignedUser).where(
            ProjectAssignedUser.project_id == project.id, ProjectAssignedUser.user_id == actor.id
        )
    ).first()
    if project.owner_id != actor.id and member is None:
        raise AppGovernanceDenied()
    personal = connection.ownership == "personal"
    if personal:
        if connection.organization_id is not None or connection.owner_id != actor.id:
            raise AppGovernanceDenied()
        if unattended:
            shared = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser)
                .where(ProjectAssignedUser.project_id == project.id, ProjectAssignedUser.user_id != actor.id)
                .limit(1)
            ).first()
            if project.organization_id is not None or project.owner_id != actor.id or shared is not None:
                raise AppGovernanceDenied()
    elif connection.ownership == "organization":
        if project.organization_id is None or connection.organization_id != project.organization_id:
            raise AppGovernanceDenied()
        _organization(db, connection.organization_id)
    else:
        raise AppGovernanceDenied()
    require_app_allowed(db, project, approved=approved, personal=personal_app)
    return connection
