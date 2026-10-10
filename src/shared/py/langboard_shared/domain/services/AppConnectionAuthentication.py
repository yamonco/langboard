"""Native connection identity. Authentication alone never grants a capability."""

from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from json import dumps
from secrets import token_urlsafe
from langboard_sdk.governance import declaration_trust_fingerprint
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ..models import AppConnection, AppDefinition, User
from ..models.AppConnectionCredential import AppConnectionCredential
from .AppGovernance import AppGovernanceDenied, _actor, _authorize, _current, _organization, current_policy
from .AppManifest import APP_MANIFESTS


@dataclass(frozen=True)
class AuthenticatedAppConnection:
    app_key: str
    connection_id: int
    credential_id: int
    owner_id: int
    organization_id: int | None


def _connection(db, identifier):
    row = _current(db, AppConnection, identifier, for_update=False)
    if row is None or row.state != "connected":
        raise AppGovernanceDenied()
    owner = _current(db, User, row.owner_id, for_update=False)
    if owner is None or owner.deleted_at or not owner.activated_at:
        raise AppGovernanceDenied()
    definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == row.app_key)).first()
    if definition is not None:
        if not definition.is_enabled:
            raise AppGovernanceDenied()
    elif row.app_key not in APP_MANIFESTS:
        raise AppGovernanceDenied()
    if row.ownership == "organization":
        if row.organization_id is None:
            raise AppGovernanceDenied()
        _organization(db, row.organization_id, for_update=False)
    elif row.ownership != "personal" or row.organization_id is not None:
        raise AppGovernanceDenied()
    if current_policy(db, row.organization_id)["effective_mode"] == "disabled":
        raise AppGovernanceDenied()
    return row


def _manage(db, actor, connection):
    current = _actor(db, actor)
    if connection.ownership == "personal":
        if current.id != connection.owner_id:
            raise AppGovernanceDenied()
    else:
        _authorize(db, current, connection.organization_id)


def _identity_hash(db, connection):
    definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == connection.app_key)).first()
    try:
        trust = declaration_trust_fingerprint(definition.declaration) if definition else "builtin"
    except ValueError as exc:
        raise AppGovernanceDenied() from exc
    identity = {
        "app_key": connection.app_key,
        "owner_id": int(connection.owner_id),
        "ownership": connection.ownership,
        "organization_id": connection.organization_id,
        "instance_url": connection.instance_url,
        "external_account_id": connection.external_account_id,
        "connection_revision": str(connection.updated_at),
        "trust": trust,
    }
    return sha256(dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_connection_credential(actor, connection_id, *, expires_in_seconds=3600):
    if type(expires_in_seconds) is not int or not 60 <= expires_in_seconds <= 86400:
        raise ValueError("Credential lifetime must be 60 to 86400 seconds")
    with DbSession.atomic() as db:
        connection = _connection(db, connection_id)
        _manage(db, actor, connection)
        token = "lbac_" + token_urlsafe(32)
        row = AppConnectionCredential(
            connection_id=connection.id,
            issued_by=actor.id,
            token_hash=sha256(token.encode()).hexdigest(),
            identity_hash=_identity_hash(db, connection),
            expires_at=SafeDateTime.now() + timedelta(seconds=expires_in_seconds),
        )
        db.insert(row)
        return {
            "credential_uid": row.get_uid(),
            "connection_uid": connection.get_uid(),
            "token": token,
            "expires_at": row.expires_at.isoformat(),
        }


def revoke_connection_credential(actor, connection_id, credential_id):
    with DbSession.atomic() as db:
        # Revocation remains possible after policy, app or connection disablement.
        connection = _current(db, AppConnection, connection_id, for_update=False)
        if connection is None:
            raise AppGovernanceDenied()
        _manage(db, actor, connection)
        row = _current(db, AppConnectionCredential, credential_id)
        if row is None or row.connection_id != connection.id:
            raise AppGovernanceDenied()
        if row.revoked_at is None:
            row.revoked_at = SafeDateTime.now()
            db.update(row)
        return {"credential_uid": row.get_uid(), "revoked": True}


def authenticate_connection_credential(token: str) -> AuthenticatedAppConnection:
    if not isinstance(token, str) or len(token) != 48 or not token.startswith("lbac_"):
        raise AppGovernanceDenied()
    with DbSession.atomic() as db:
        row = db.exec(
            SqlBuilder.select.table(AppConnectionCredential).where(
                AppConnectionCredential.token_hash == sha256(token.encode()).hexdigest(),
            )
        ).first()
        if row is None or row.revoked_at:
            raise AppGovernanceDenied()
        expires_at = row.expires_at
        # SQLite drops timezone offsets; the credential writer always stores UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= SafeDateTime.now():
            raise AppGovernanceDenied()
        connection = _connection(db, row.connection_id)
        if row.identity_hash != _identity_hash(db, connection):
            raise AppGovernanceDenied()
        return AuthenticatedAppConnection(
            app_key=connection.app_key,
            connection_id=int(connection.id),
            credential_id=int(row.id),
            owner_id=int(connection.owner_id),
            organization_id=int(connection.organization_id) if connection.organization_id is not None else None,
        )
