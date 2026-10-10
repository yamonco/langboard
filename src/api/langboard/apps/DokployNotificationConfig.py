"""Explicit, ephemeral comparison of the official Dokploy notification configuration."""

import hmac
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from langboard_shared.core.db import DbSession
from . import DokployConnection as connection
from . import DokployWebhook as webhook
from .MetadataTransport import MetadataUnavailable, approved_instance, read_json


def _callback(value, receiver_path):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Invalid callback URL")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        raise ValueError("Invalid callback URL") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or "%" in value
        or "\\" in value
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or not parsed.path.endswith(receiver_path)
    ):
        raise ValueError("Invalid callback URL")
    return value


def _scope(
    service, actor, project_uid, connection_uid, expected_revision, expected_binding_revision, expected_config_revision
):
    conn, binding, resources, config = webhook._scope(service, actor, project_uid, connection_uid)
    webhook._granted(binding, resources)
    webhook._expected(conn, binding, config, expected_revision, expected_binding_revision, expected_config_revision)
    if (
        config is None
        or config.state != "enabled"
        or not config.notification_id
        or config.connection_revision != connection._revision(conn)
        or config.binding_revision != binding.edit_revision()
        or config.resource_revision != webhook._resource_revision(resources)
        or config.credential_reference == conn.credential_reference
    ):
        raise connection.DokployUnavailable()
    connection._id(config.notification_id)
    approved_instance(conn.instance_url)
    reference = service.secret_reference._find(actor, config.credential_reference, lock=True)
    if reference.state != "active" or reference.revision != config.secret_revision:
        raise connection.DokployUnavailable()
    management = service.secret_reference._find(actor, conn.credential_reference, lock=True)
    return (
        conn,
        config,
        (
            management.revision,
            reference.revision,
            config.get_uid(),
            config.notification_id,
            config.credential_reference,
        ),
    )


def _checks(data, notification_id, callback, receiver):
    data = data if isinstance(data, dict) else {}
    custom = data.get("custom")
    custom = custom if isinstance(custom, dict) else {}
    headers = custom.get("headers")
    valid = (
        isinstance(headers, dict)
        and len(headers) <= 100
        and all(
            isinstance(key, str)
            and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", key)
            and isinstance(value, str)
            and len(value) <= 4103
            and not any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            for key, value in headers.items()
        )
    )
    authorization = [value for key, value in headers.items() if key.lower() == "authorization"] if valid else []
    return {
        "notification_id": data.get("notificationId") == notification_id,
        "custom_type": (
            data.get("notificationType") == "custom"
            and isinstance(data.get("customId"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", data["customId"]) is not None
            and custom.get("customId") == data["customId"]
        ),
        "endpoint": custom.get("endpoint") == callback,
        "authorization": len(authorization) == 1
        and hmac.compare_digest(authorization[0].encode(), ("Bearer " + receiver).encode()),
        "build_success": data.get("appDeploy") is True,
        "build_error": data.get("appBuildError") is True,
    }


def verify(
    service,
    actor,
    project_uid,
    connection_uid,
    expected_revision,
    expected_binding_revision,
    expected_config_revision,
    callback_url,
):
    if (
        not isinstance(expected_revision, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_revision)
        or not isinstance(expected_binding_revision, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_binding_revision)
        or type(expected_config_revision) is not int
        or expected_config_revision < 1
    ):
        raise ValueError("Invalid configuration revision")
    args = (
        service,
        actor,
        project_uid,
        connection_uid,
        expected_revision,
        expected_binding_revision,
        expected_config_revision,
    )
    with DbSession.atomic():
        conn, config, snapshot = _scope(*args)
        callback = _callback(callback_url, "/apps/dokploy/notifications/" + config.get_uid())
        token, management_revision = connection._credential(service, actor, conn.credential_reference)
        receiver, receiver_revision = connection._credential(service, actor, config.credential_reference)
        if (management_revision, receiver_revision) != snapshot[:2]:
            raise connection.DokployConflict()
        if hmac.compare_digest(token, receiver):
            raise connection.DokployUnavailable()
        base, notification_id = approved_instance(conn.instance_url), config.notification_id
    # No database transaction or row lock crosses external I/O. Never fetch the callback.
    checks = None
    try:
        data, _ = read_json(
            base,
            "/api/notification.one",
            {"x-api-key": token, "Accept": "application/json"},
            {"notificationId": notification_id},
        )
        checks = _checks(data, notification_id, callback, receiver)
    except (MetadataUnavailable, httpx.HTTPError):
        pass
    with DbSession.atomic():
        _, _, current = _scope(*args)
        if current != snapshot:
            raise connection.DokployConflict()
        return {
            "provider_config": "unavailable" if checks is None else "matched" if all(checks.values()) else "mismatch",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "config_revision": expected_config_revision,
            "connection_revision": expected_revision,
            "binding_revision": expected_binding_revision,
            "checks": checks,
        }
