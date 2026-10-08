"""Authenticated local notification receipts. Generic notifications never create signals."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import (
    AppConnection,
    AppResourceBinding,
    BoardAppBinding,
    DokployNotificationReceipt,
    DokployWebhookBinding,
    User,
)
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from . import DokployConnection as connection


MAX_BODY = 65536


def _scope(service, actor, project_uid, connection_uid, *, allow_unconfigured=False):
    board = connection._board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        conn = connection._connection(db, actor, connection_uid, lock=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "dokploy",
            )
            .with_for_update()
        ).first()
        if binding is None:
            if allow_unconfigured:
                secret = service.secret_reference._find(actor, conn.credential_reference, lock=True)
                if secret.state != "active":
                    raise connection.DokployUnavailable()
                return conn, None, [], None
            raise connection.DokployUnavailable()
        resources = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == conn.id,
                AppResourceBinding.resource_type.in_(("application", "compose")),
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.access_state == "granted",
            )
            .order_by(AppResourceBinding.id)
            .with_for_update()
        ).all()
        config = db.exec(
            SqlBuilder.select.table(DokployWebhookBinding)
            .where(
                DokployWebhookBinding.board_binding_id == binding.id,
                DokployWebhookBinding.connection_id == conn.id,
            )
            .with_for_update()
        ).first()
        secret = service.secret_reference._find(actor, conn.credential_reference, lock=True)
        if secret.state != "active":
            raise connection.DokployUnavailable()
    return conn, binding, resources, config


def _granted(binding, resources):
    if (
        binding.state not in {"enabled", "needs_attention"}
        or not resources
        or not {
            "resources.read",
            "signals.read",
            "deployments.read",
        }.issubset(binding.granted_capabilities)
    ):
        raise connection.DokployUnavailable()


def _resource_revision(resources):
    return hashlib.sha256(
        json.dumps(
            [[int(row.id), row.access_revision, row.resource_path] for row in resources], sort_keys=True
        ).encode()
    ).hexdigest()


def _expected(conn, binding, config, expected_revision, expected_binding_revision, expected_config_revision):
    if (
        connection._revision(conn) != expected_revision
        or binding.edit_revision() != expected_binding_revision
        or (config.config_revision if config else 0) != expected_config_revision
    ):
        raise connection.DokployConflict()


def _health(db, conn, binding, resources, config):
    last = (
        db.exec(
            SqlBuilder.select.table(DokployNotificationReceipt)
            .where(
                DokployNotificationReceipt.config_id == config.id,
            )
            .order_by(DokployNotificationReceipt.received_at.desc())
            .limit(1)
        ).first()
        if config
        else None
    )
    return {
        "config_uid": config.get_uid() if config else None,
        "config_revision": config.config_revision if config else 0,
        "state": config.state if config else "unconfigured",
        "receiver_path": "/apps/dokploy/notifications/" + config.get_uid() if config else None,
        "notification_id": config.notification_id if config else None,
        "provider_config": "unknown",
        "last_received_at": last.received_at if last else None,
        "local_evidence": "authenticated_notification_receipt",
        "connection_state": conn.state,
        "connection_revision": connection._revision(conn),
        "binding_revision": binding.edit_revision() if binding else None,
        "resources": [{"resource_uid": row.get_uid(), "health": row.health} for row in resources],
    }


def health(service, actor, project_uid, connection_uid):
    with DbSession.atomic() as db:
        conn, binding, resources, config = _scope(service, actor, project_uid, connection_uid, allow_unconfigured=True)
        if config:
            reference = service.secret_reference._find(actor, config.credential_reference, lock=True)
            if reference.state != "active":
                raise connection.DokployUnavailable()
        return _health(db, conn, binding, resources, config)


def configure(
    service,
    actor,
    project_uid,
    connection_uid,
    expected_revision,
    expected_binding_revision,
    expected_config_revision,
    credential_reference,
    notification_id=None,
):
    if notification_id is not None:
        connection._id(notification_id)
    with DbSession.atomic() as db:
        conn, binding, resources, config = _scope(service, actor, project_uid, connection_uid)
        _granted(binding, resources)
        _expected(conn, binding, config, expected_revision, expected_binding_revision, expected_config_revision)
        if credential_reference == conn.credential_reference:
            raise ValueError("Receiver credential must be separate")
        token, revision = connection._credential(service, actor, credential_reference)
        management, _ = connection._credential(service, actor, conn.credential_reference)
        if hmac.compare_digest(token, management):
            raise ValueError("Receiver credential must be separate")
        config = config or DokployWebhookBinding(
            board_binding_id=binding.id,
            connection_id=conn.id,
            config_revision=0,
            credential_reference=credential_reference,
            secret_revision=revision,
            connection_revision=connection._revision(conn),
            binding_revision=binding.edit_revision(),
            resource_revision=_resource_revision(resources),
        )
        config.credential_reference, config.secret_revision = credential_reference, revision
        config.connection_revision, config.binding_revision = connection._revision(conn), binding.edit_revision()
        config.resource_revision = _resource_revision(resources)
        config.notification_id, config.state = notification_id, "enabled"
        config.config_revision += 1
        db.insert(config) if expected_config_revision == 0 else db.update(config)
        service.secret_reference.audit_binding(
            actor,
            credential_reference,
            revision,
            source=SecretAuditSource("app_connection", conn.get_uid()),
        )
        return _health(db, conn, binding, resources, config)


def disable(
    service, actor, project_uid, connection_uid, expected_revision, expected_binding_revision, expected_config_revision
):
    with DbSession.atomic() as db:
        conn, binding, resources, config = _scope(service, actor, project_uid, connection_uid)
        _expected(conn, binding, config, expected_revision, expected_binding_revision, expected_config_revision)
        if config is None:
            raise connection.DokployUnavailable()
        config.state = "disabled"
        config.config_revision += 1
        db.update(config)
        return _health(db, conn, binding, resources, config)


def _authenticate(service, config_uid, authorization):
    connection._id(config_uid)
    with DbSession.use(readonly=False) as db:
        config = db.exec(
            SqlBuilder.select.table(DokployWebhookBinding).where(
                DokployWebhookBinding.id == InfraHelper.convert_id(config_uid),
            )
        ).first()
        if config is None:
            raise connection.DokployUnavailable()
        conn = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == config.connection_id)).first()
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.id == config.board_binding_id)
        ).first()
        actor = db.exec(SqlBuilder.select.table(User).where(User.id == conn.owner_id)).first() if conn else None
        if actor is None or binding is None:
            raise connection.DokployUnavailable()
    conn, binding, resources, current = _scope(
        service, actor, InfraHelper.convert_uid(binding.project_id), conn.get_uid()
    )
    _granted(binding, resources)
    if (
        current is None
        or current.id != config.id
        or current.state != "enabled"
        or current.connection_revision != connection._revision(conn)
        or current.binding_revision != binding.edit_revision()
        or current.resource_revision != _resource_revision(resources)
        or current.credential_reference == conn.credential_reference
    ):
        raise connection.DokployUnavailable()
    reference = service.secret_reference._find(actor, current.credential_reference, lock=True)
    if reference.state != "active" or reference.revision != current.secret_revision:
        raise connection.DokployUnavailable()
    token = service.secret_reference.resolve_for_runtime(
        actor,
        current.credential_reference,
        source=SecretAuditSource("api", "dokploy_notification"),
    ).get_secret_value()
    if (
        not isinstance(authorization, str)
        or len(authorization) > 4103
        or not hmac.compare_digest(
            authorization.encode(),
            ("Bearer " + token).encode(),
        )
    ):
        raise connection.DokployUnavailable()
    return current


def authenticate(service, config_uid, authorization):
    with DbSession.atomic():
        return _authenticate(service, config_uid, authorization).config_revision


def _payload(body):
    if len(body) > MAX_BODY:
        raise ValueError("Oversize notification")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    try:
        data = json.loads(body, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Invalid notification") from None
    allowed = {
        "type",
        "status",
        "title",
        "message",
        "projectName",
        "applicationName",
        "applicationType",
        "buildLink",
        "timestamp",
        "date",
        "domains",
        "errorMessage",
    }
    if (
        not isinstance(data, dict)
        or not set(data).issubset(allowed)
        or data.get("type") != "build"
        or data.get("status") not in ("success", "error")
        or any(not isinstance(value, str) or len(value) > 8192 for value in data.values())
    ):
        raise ValueError("Unsupported notification")
    return data["type"], data["status"]


def receive(service, config_uid, authorization, body, expected_config_revision):
    with DbSession.atomic() as db:
        config = _authenticate(service, config_uid, authorization)
        if config.config_revision != expected_config_revision:
            raise connection.DokployUnavailable()
        notification_type, status = _payload(body)
        digest = hashlib.sha256(body).hexdigest()
        receipt = db.exec(
            SqlBuilder.select.table(DokployNotificationReceipt).where(
                DokployNotificationReceipt.config_id == config.id,
                DokployNotificationReceipt.config_revision == config.config_revision,
                DokployNotificationReceipt.payload_digest == digest,
            )
        ).first()
        duplicate = receipt is not None
        if receipt is None:
            receipt = DokployNotificationReceipt(
                config_id=config.id,
                config_revision=config.config_revision,
                payload_digest=digest,
                received_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                notification_type=notification_type,
                status=status,
            )
            db.insert(receipt)
        return {"receipt_uid": receipt.get_uid(), "received_at": receipt.received_at, "duplicate": duplicate}
