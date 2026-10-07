"""Verified lifecycle input; delivery persistence and consumers remain separate."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from uuid import UUID
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from .GitHubInstallation import connection_revision
from .GitHubManifest import GitHubManifestUnavailable


MAX_BODY = 1024 * 1024
ACTIONS = {
    "installation": {"created", "deleted", "suspend", "unsuspend", "new_permissions_accepted"},
    "installation_repositories": {"added", "removed"},
}


@dataclass(frozen=True)
class VerifiedLifecycle:
    connection_uid: str
    connection_revision: str
    delivery_id: str
    payload_digest: str
    event: str
    action: str
    app_id: int
    installation_id: int
    account_id: int
    added_repository_ids: tuple[int, ...]
    removed_repository_ids: tuple[int, ...]


def _positive(value):
    if type(value) is not int or value <= 0:
        raise GitHubManifestUnavailable()
    return value


def _repositories(value):
    if not isinstance(value, list) or len(value) > 1000:
        raise GitHubManifestUnavailable()
    ids = tuple(_positive(item.get("id")) for item in value)
    if len(set(ids)) != len(ids):
        raise GitHubManifestUnavailable()
    return ids


def verify_lifecycle(service, actor, connection_uid, body: bytes, signature: str, event: str, delivery_id: str):
    """Only trusted host code supplies actor; no external caller identity fields."""
    try:
        if not isinstance(body, bytes) or not body or len(body) > MAX_BODY:
            raise GitHubManifestUnavailable()
        if not isinstance(signature, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
            raise GitHubManifestUnavailable()
        if event not in ACTIONS or str(UUID(delivery_id)) != delivery_id.lower():
            raise GitHubManifestUnavailable()
        with DbSession.use(readonly=False) as db:
            connection = db.exec(
                SqlBuilder.select.table(AppConnection).where(
                    AppConnection.id == InfraHelper.convert_id(connection_uid),
                    AppConnection.app_key == "github",
                    AppConnection.owner_id == actor.id,
                )
            ).first()
        if (
            connection is None
            or connection.state not in {"pending", "connected"}
            or not connection.credential_reference
        ):
            raise GitHubManifestUnavailable()
        revision = connection_revision(connection)
        credential = json.loads(
            service.secret_reference.resolve_for_runtime(
                actor, connection.credential_reference, source=SecretAuditSource("app_connection", connection_uid)
            ).get_secret_value()
        )
        app_id = _positive(credential.get("id"))
        secret = credential.get("webhook_secret")
        if str(app_id) != connection.external_account_id or not isinstance(secret, str) or not secret:
            raise GitHubManifestUnavailable()
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise GitHubManifestUnavailable()
        # Decode only after verification of the unmodified bytes.
        payload = json.loads(body)
        action = payload.get("action")
        if action not in ACTIONS[event]:
            raise GitHubManifestUnavailable()
        installation = payload.get("installation", {})
        if _positive(installation.get("app_id")) != app_id:
            raise GitHubManifestUnavailable()
        account = installation.get("account", {})
        if account.get("type") not in {"User", "Organization"}:
            raise GitHubManifestUnavailable()
        added = _repositories(payload.get("repositories_added", []))
        removed = _repositories(payload.get("repositories_removed", []))
        if set(added) & set(removed) or event == "installation" and (added or removed):
            raise GitHubManifestUnavailable()
        if event == "installation_repositories" and (action == "added" and removed or action == "removed" and added):
            raise GitHubManifestUnavailable()
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection.id)).first()
            if current is None or connection_revision(current) != revision:
                raise GitHubManifestUnavailable()
        return VerifiedLifecycle(
            connection_uid,
            revision,
            str(UUID(delivery_id)),
            hashlib.sha256(body).hexdigest(),
            event,
            action,
            app_id,
            _positive(installation.get("id")),
            _positive(account.get("id")),
            added,
            removed,
        )
    except Exception:
        raise GitHubManifestUnavailable() from None
