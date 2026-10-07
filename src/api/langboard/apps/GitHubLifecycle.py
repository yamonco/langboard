"""Verified lifecycle input; delivery persistence and consumers remain separate."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from uuid import UUID
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, GitHubLifecycleReceipt, User
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from sqlalchemy import update
from .GitHubInstallation import connection_revision
from .GitHubManifest import GitHubManifestUnavailable


MAX_BODY = 1024 * 1024
ACTIONS = {
    "installation": {"created", "deleted", "suspend", "unsuspend", "new_permissions_accepted"},
    "installation_repositories": {"added", "removed"},
    "ping": {"ping"},
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
    installation_id: int | None
    account_id: int | None
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
        if event == "ping":
            if payload.get("action") is not None or payload.get("installation") is not None:
                raise GitHubManifestUnavailable()
            hook_id = _positive(payload.get("hook_id"))
            hook = payload.get("hook", {})
            if _positive(hook.get("id", hook_id)) != hook_id:
                raise GitHubManifestUnavailable()
            action, installation_id, account_id = "ping", None, None
            added, removed = (), ()
        else:
            action = payload.get("action")
            if action not in ACTIONS[event]:
                raise GitHubManifestUnavailable()
            installation = payload.get("installation", {})
            if _positive(installation.get("app_id")) != app_id:
                raise GitHubManifestUnavailable()
            account = installation.get("account", {})
            if account.get("type") not in {"User", "Organization"}:
                raise GitHubManifestUnavailable()
            installation_id, account_id = _positive(installation.get("id")), _positive(account.get("id"))
            added = _repositories(payload.get("repositories_added", []))
            removed = _repositories(payload.get("repositories_removed", []))
            if set(added) & set(removed) or event == "installation" and (added or removed):
                raise GitHubManifestUnavailable()
            if event == "installation_repositories" and (
                action == "added" and removed or action == "removed" and added
            ):
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
            installation_id,
            account_id,
            added,
            removed,
        )
    except Exception:
        raise GitHubManifestUnavailable() from None


class GitHubDeliveryConflict(Exception):
    pass


def receive_lifecycle(service, actor, connection_uid, body: bytes, signature: str, event: str, delivery_id: str):
    """Atomically record verified input and invalidate affected resource evidence once."""
    verified = verify_lifecycle(service, actor, connection_uid, body, signature, event, delivery_id)
    with DbSession.atomic() as db:
        connection = db.exec(
            SqlBuilder.select.table(AppConnection)
            .where(AppConnection.id == InfraHelper.convert_id(connection_uid), AppConnection.owner_id == actor.id)
            .with_for_update()
        ).first()
        if connection is None or connection_revision(connection) != verified.connection_revision:
            raise GitHubManifestUnavailable()
        values = {
            "payload_digest": verified.payload_digest,
            "event": verified.event,
            "action": verified.action,
            "app_id": str(verified.app_id),
            "installation_id": str(verified.installation_id) if verified.installation_id is not None else "",
            "account_id": str(verified.account_id) if verified.account_id is not None else "",
            "added_repository_ids": list(verified.added_repository_ids),
            "removed_repository_ids": list(verified.removed_repository_ids),
        }
        receipt = db.exec(
            SqlBuilder.select.table(GitHubLifecycleReceipt).where(
                GitHubLifecycleReceipt.connection_id == connection.id,
                GitHubLifecycleReceipt.delivery_id == verified.delivery_id,
            )
        ).first()
        if receipt is not None:
            if any(getattr(receipt, key) != value for key, value in values.items()):
                raise GitHubDeliveryConflict()
            if not receipt.invalidated:
                _invalidate_resources(db, receipt)
            return {"receipt_uid": receipt.get_uid(), "duplicate": True}
        receipt = GitHubLifecycleReceipt(
            connection_id=connection.id,
            connection_revision=verified.connection_revision,
            delivery_id=verified.delivery_id,
            **values,
        )
        db.insert(receipt)
        _invalidate_resources(db, receipt)
        return {"receipt_uid": receipt.get_uid(), "duplicate": False}


def receive_external_lifecycle(
    service, body: bytes, signature: str, event: str, delivery_id: str, target_app_id: str | None = None
):
    """Unverified App ID routes a bounded candidate; only HMAC verification authorizes receipt."""
    try:
        if not isinstance(body, bytes) or not body or len(body) > MAX_BODY:
            raise GitHubManifestUnavailable()
        if not isinstance(signature, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
            raise GitHubManifestUnavailable()
        if event not in ACTIONS or str(UUID(delivery_id)) != delivery_id.lower():
            raise GitHubManifestUnavailable()
        candidate = json.loads(body)
        if event == "ping":
            if not isinstance(target_app_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", target_app_id):
                raise GitHubManifestUnavailable()
            app_id = int(target_app_id)
        else:
            app_id = _positive(candidate.get("installation", {}).get("app_id"))
        with DbSession.use(readonly=False) as db:
            connections = db.exec(
                SqlBuilder.select.table(AppConnection)
                .where(
                    AppConnection.app_key == "github",
                    AppConnection.external_account_id == str(app_id),
                    AppConnection.state.in_(["pending", "connected"]),
                )
                .limit(2)
            ).all()
            # No secret scan or guessed owner when a reusable App has ambiguous connections.
            if len(connections) != 1:
                raise GitHubManifestUnavailable()
            connection = connections[0]
            actor = db.exec(SqlBuilder.select.table(User).where(User.id == connection.owner_id)).first()
            if actor is None or actor.deleted_at is not None or actor.activated_at is None:
                raise GitHubManifestUnavailable()
    except Exception:
        raise GitHubManifestUnavailable() from None
    return receive_lifecycle(service, actor, connection.get_uid(), body, signature, event, delivery_id)


def _invalidate_resources(db, receipt):
    """Events invalidate evidence; only a fresh scoped GitHub query can restore access."""
    if receipt.event == "ping":
        receipt.invalidated = True
        db.update(receipt)
        return
    conditions = [
        AppResourceBinding.connection_id == receipt.connection_id,
        AppResourceBinding.resource_type == "repository",
        AppResourceBinding.is_selected == True,  # noqa: E712
        AppResourceBinding.resource_path[0]["type"].as_string() == "installation",
        AppResourceBinding.resource_path[0]["id"].as_string() == receipt.installation_id,
        AppResourceBinding.resource_path[1]["type"].as_string() == "account",
        AppResourceBinding.resource_path[1]["id"].as_string() == receipt.account_id,
    ]
    if receipt.event == "installation_repositories":
        ids = [str(value) for value in (*receipt.added_repository_ids, *receipt.removed_repository_ids)]
        conditions.append(AppResourceBinding.external_resource_id.in_(ids))
    # One scoped DB update across selected boards; no per-resource API/token loop.
    db.exec(
        update(AppResourceBinding)
        .where(*conditions)
        .values(
            access_state="unknown",
            health="unavailable",
            access_revision=AppResourceBinding.access_revision + 1,
        ),
        execution_options={"synchronize_session": False},
    )
    receipt.invalidated = True
    db.update(receipt)
