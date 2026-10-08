"""Signed check evidence for an explicitly selected board resource; never stage transitions."""
import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, AppSignal, BoardAppBinding, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.helpers import InfraHelper
from .GitHubInstallation import connection_revision
from .GitHubLifecycle import GitHubDeliveryConflict, _positive, verify_signed_payload
from .GitHubManifest import GitHubManifestUnavailable


CONCLUSIONS = {"success", "failure", "neutral", "cancelled", "timed_out", "action_required", "stale", "skipped"}


def _scope(service, db, project_uid, connection_uid, resource_uid, actor=None, *, lock=False):
    def query(model):
        statement = SqlBuilder.select.table(model)
        return statement.with_for_update() if lock else statement

    # Discover identity from the stored connection, never the webhook sender.
    connection_id = InfraHelper.convert_id(connection_uid)
    stored = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection_id)).first()
    if stored is None or stored.app_key != "github":
        raise GitHubManifestUnavailable()
    owner = db.exec(SqlBuilder.select.table(User).where(User.id == stored.owner_id)).first()
    if owner is None:
        raise GitHubManifestUnavailable()
    board = service.workflow_stage._authorized_app_board(owner, project_uid, ProjectRoleAction.Update, lock=lock)
    if board is None or actor is not None and service.workflow_stage._authorized_app_board(
        actor, project_uid, ProjectRoleAction.Read, lock=lock
    ) is None:
        raise GitHubManifestUnavailable()
    connection = db.exec(query(AppConnection).where(AppConnection.id == connection_id)).first()
    binding = db.exec(query(BoardAppBinding).where(
        BoardAppBinding.project_id == board.id, BoardAppBinding.app_key == "github",
    )).first()
    if (
        connection is None or connection.owner_id != owner.id or connection.state != "connected"
        or binding is None or binding.state not in {"enabled", "needs_attention"}
        or "signals.read" not in binding.granted_capabilities
    ):
        raise GitHubManifestUnavailable()
    resource = db.exec(query(AppResourceBinding).where(
        AppResourceBinding.id == InfraHelper.convert_id(resource_uid),
        AppResourceBinding.board_binding_id == binding.id,
        AppResourceBinding.connection_id == connection.id,
        AppResourceBinding.resource_type == "repository",
        AppResourceBinding.is_selected == True,  # noqa: E712
        AppResourceBinding.access_state == "granted",
    )).first()
    if resource is None:
        raise GitHubManifestUnavailable()
    return owner, connection, resource


def normalize_check(payload, body, delivery_id):
    if payload.get("action") != "completed":
        raise GitHubManifestUnavailable()
    check = payload["check_run"]
    # check_run.app is the producer, not the receiving App; installation is an InstallationLite.
    conclusion = check["conclusion"]
    if check.get("status") != "completed" or conclusion not in CONCLUSIONS:
        raise GitHubManifestUnavailable()
    sha = check["head_sha"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise GitHubManifestUnavailable()
    timestamp = check["completed_at"]
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise GitHubManifestUnavailable()
    occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if occurred_at.tzinfo is None:
        raise GitHubManifestUnavailable()
    return dict(
        provider="github", event_id=str(UUID(delivery_id)), event_type="check.completed",
        occurred_at=occurred_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        external_id=str(_positive(check["id"])), outcome=conclusion, commit_sha=sha,
        payload_digest=hashlib.sha256(body).hexdigest(),
    )


def receive_check(service, project_uid, connection_uid, resource_uid, body, signature, event, delivery_id):
    """One configured webhook resource. Current authority and SecretRef revision fenced at commit."""
    try:
        if event != "check_run":
            raise GitHubManifestUnavailable()
        with DbSession.use(readonly=False) as db:
            owner, connection, resource = _scope(service, db, project_uid, connection_uid, resource_uid)
            resource_revision = resource.access_revision
            resource_path = [dict(part) for part in resource.resource_path]
        secret_meta = service.secret_reference.get_metadata(owner, connection.credential_reference)
        payload, connection, revision, _ = verify_signed_payload(
            service, owner, connection_uid, body, signature, delivery_id
        )
        values = normalize_check(payload, body, delivery_id)
        installation_id = str(_positive(payload["installation"]["id"]))
        account_id = str(_positive(payload["repository"]["owner"]["id"]))
        repository_id = str(_positive(payload["repository"]["id"]))
        path = resource.resource_path
        if (
            len(path) != 3 or path[0].get("type") != "installation" or path[0].get("id") != installation_id
            or path[1].get("type") != "account" or path[1].get("id") != account_id
            or path[2].get("type") != "repository" or path[2].get("id") != repository_id
            or repository_id != resource.external_resource_id
        ):
            raise GitHubManifestUnavailable()
    except Exception:
        raise GitHubManifestUnavailable() from None
    with DbSession.atomic() as db:
        _, current, resource = _scope(service, db, project_uid, connection_uid, resource_uid, lock=True)
        if (
            connection_revision(current) != revision or resource.access_revision != resource_revision
            or resource.resource_path != resource_path
        ):
            raise GitHubManifestUnavailable()
        try:
            current_meta = service.secret_reference._find(owner, current.credential_reference, lock=True).metadata()
        except Exception:
            raise GitHubManifestUnavailable() from None
        if current_meta["state"] != "active" or current_meta["revision"] != secret_meta["revision"]:
            raise GitHubManifestUnavailable()
        existing = db.exec(SqlBuilder.select.table(AppSignal).where(
            AppSignal.resource_id == resource.id, AppSignal.event_id == values["event_id"],
        )).first()
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items()):
                raise GitHubDeliveryConflict()
            return {"signal_uid": existing.get_uid(), "duplicate": True}
        signal = AppSignal(resource_id=resource.id, **values)
        db.insert(signal)
        return {"signal_uid": signal.get_uid(), "duplicate": False}


def list_signals(service, actor, project_uid, connection_uid, resource_uid, after=None):
    with DbSession.use(readonly=False) as db:
        owner, connection, resource = _scope(service, db, project_uid, connection_uid, resource_uid, actor)
        try:
            metadata = service.secret_reference._find(owner, connection.credential_reference, lock=True).metadata()
        except Exception:
            raise GitHubManifestUnavailable() from None
        if metadata["state"] != "active":
            raise GitHubManifestUnavailable()
        query = SqlBuilder.select.table(AppSignal).where(AppSignal.resource_id == resource.id)
        if after is not None:
            if not isinstance(after, str) or not re.fullmatch(r"[0-9A-Za-z]{11}", after):
                raise ValueError("Invalid signal cursor")
            cursor_id = InfraHelper.convert_id(after)
            if db.exec(query.where(AppSignal.id == cursor_id).limit(1)).first() is None:
                raise ValueError("Invalid signal cursor")
            query = query.where(AppSignal.id < cursor_id)
        rows = db.exec(query.order_by(AppSignal.id.desc()).limit(26)).all()
        return {
            "items": [{
                "signal_uid": row.get_uid(), "provider": row.provider, "event_id": row.event_id,
                "event_type": row.event_type, "occurred_at": row.occurred_at,
                "connection_uid": connection.get_uid(), "resource_uid": resource.get_uid(),
                "external_id": row.external_id, "outcome": row.outcome, "commit_sha": row.commit_sha,
            } for row in rows[:25]],
            "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
        }
