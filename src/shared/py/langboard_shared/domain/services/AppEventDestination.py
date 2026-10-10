"""Bind existing administrator-managed webhook settings to an approved app origin."""

from hashlib import sha256
from json import dumps
from urllib.parse import urlsplit
from langboard_sdk.governance import declaration_trust_fingerprint
from ...core.db import DbSession, SqlBuilder
from ..models import AppConnection, AppDefinition, AppEventDestination, User, WebhookSetting
from .AppConnectionAuthentication import _connection
from .AppGovernance import AppGovernanceConflict, AppGovernanceDenied, _actor, _current


APP_EXECUTION_EVENT = "io.langboard.app.execution.requested.v1"


def _target_revision(setting):
    return sha256(dumps([setting.url, setting.secret_id, setting.events], sort_keys=True).encode()).hexdigest()


def current_destination(db, connection):
    connection = _connection(db, connection.id)
    row = db.exec(
        SqlBuilder.select.table(AppEventDestination)
        .where(
            AppEventDestination.connection_id == connection.id,
        )
        .with_for_update()
    ).first()
    setting = _current(db, WebhookSetting, row.webhook_id) if row else None
    definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == connection.app_key)).first()
    if (
        row is None
        or not row.is_enabled
        or setting is None
        or not setting.secret_id
        or definition is None
        or not definition.is_enabled
    ):
        raise AppGovernanceDenied()
    declaration = definition.declaration
    if row.target_revision != _target_revision(setting) or row.trust_revision != declaration_trust_fingerprint(
        declaration
    ):
        raise AppGovernanceConflict()
    if "events.receive" not in declaration.get("capabilities", []) or APP_EXECUTION_EVENT not in (setting.events or []):
        raise AppGovernanceDenied()
    try:
        url = urlsplit(setting.url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("Invalid app event destination")
        origin = f"https://{url.hostname}" + (f":{url.port}" if url.port and url.port != 443 else "")
    except ValueError as exc:
        raise AppGovernanceDenied() from exc
    if origin not in declaration.get("trust", {}).get("data_origins", []):
        raise AppGovernanceDenied()
    return row, setting


def bind_app_event_destination(actor, connection_id, webhook_id, expected_revision):
    """Internal host configuration. Existing webhook secrets are instance-admin managed."""
    if not isinstance(actor, User):
        raise AppGovernanceDenied()
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
        raise ValueError("Invalid destination revision")
    with DbSession.atomic() as db:
        current = _actor(db, actor)
        if not current.is_admin:
            raise AppGovernanceDenied()
        connection = _current(db, AppConnection, connection_id)
        if connection is None or connection.state != "connected":
            raise AppGovernanceDenied()
        setting = _current(db, WebhookSetting, webhook_id)
        definition = db.exec(
            SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == connection.app_key)
        ).first()
        if setting is None or definition is None:
            raise AppGovernanceDenied()
        target_revision = _target_revision(setting)
        trust_revision = declaration_trust_fingerprint(definition.declaration)
        row = db.exec(
            SqlBuilder.select.table(AppEventDestination)
            .where(
                AppEventDestination.connection_id == connection.id,
            )
            .with_for_update()
        ).first()
        if (row is None and expected_revision is not None) or (row is not None and row.revision != expected_revision):
            raise AppGovernanceConflict()
        if row is None:
            row = AppEventDestination(
                connection_id=connection.id,
                webhook_id=webhook_id,
                target_revision=target_revision,
                trust_revision=trust_revision,
            )
            db.insert(row)
        elif (row.webhook_id, row.target_revision, row.trust_revision) != (webhook_id, target_revision, trust_revision):
            row.webhook_id = webhook_id
            row.target_revision = target_revision
            row.trust_revision = trust_revision
            row.revision += 1
            db.update(row)
        current_destination(db, connection)
        return {"revision": row.revision}


def prepare_app_event_signature(event_id, expected_destination_revision, *, timestamp=None):
    """Prepare exact signed bytes without sending or claiming execution authority."""
    from ...core.security import KeyVault
    from ...tasks.webhooks.WebhookTask import sign_webhook_bytes
    from ..models import AppExecutionOutbox

    if type(expected_destination_revision) is not int or expected_destination_revision < 1:
        raise ValueError("Invalid destination revision")
    with DbSession.atomic() as db:
        event = _current(db, AppExecutionOutbox, event_id)
        if event is None or event.state != "pending" or event.event_type != APP_EXECUTION_EVENT:
            raise AppGovernanceDenied()
        connection = _current(db, AppConnection, event.connection_id)
        if connection is None or connection.app_key != event.app_key:
            raise AppGovernanceDenied()
        destination, setting = current_destination(db, connection)
        if destination.revision != expected_destination_revision:
            raise AppGovernanceConflict()
        snapshot = {"destination_uid": destination.get_uid(), "revision": destination.revision}
        if event.payload.get("destination") is not None and event.payload["destination"] != snapshot:
            raise AppGovernanceConflict()
        secret = KeyVault.get_key(setting.secret_id)
        if not secret:
            raise AppGovernanceDenied()
        if event.payload.get("destination") is None:
            event.payload = {**event.payload, "destination": snapshot}
            db.update(event)
        body = dumps(event.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        body, headers = sign_webhook_bytes(body, event.get_uid(), secret, timestamp=timestamp)
        return {"body": body, "headers": headers, "url": setting.url, "destination_revision": destination.revision}
