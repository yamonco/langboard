"""Explicit bounded deployment refresh; no provider writes or workflow transitions."""

import hashlib
import json
from datetime import datetime, timezone
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppResourceBinding, AppSignal, BoardAppBinding
from langboard_shared.domain.services.AppRegistry import signal_app_allowed
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardPublisher
from . import DokployConnection as connection
from .MetadataTransport import MetadataUnavailable, read_json


def normalize_deployment(row, resource_type, external_resource_id):
    if not isinstance(row, dict) or row.get(resource_type + "Id") != external_resource_id:
        raise connection.DokployUnavailable()
    try:
        external_id = connection._id(row.get("deploymentId"))
    except ValueError:
        raise connection.DokployUnavailable() from None
    status = row.get("status")
    if not isinstance(status, str):
        raise connection.DokployUnavailable()
    if status == "running":
        started = row.get("startedAt")
        event_type = "deployment.started" if started else "deployment.queued"
        outcome = "running" if started else "queued"
        timestamp = started or row.get("createdAt")
    elif status in {"done", "error", "cancelled"}:
        event_type, outcome = {
            "done": ("deployment.succeeded", "success"),
            "error": ("deployment.failed", "failure"),
            "cancelled": ("deployment.cancelled", "cancelled"),
        }[status]
        timestamp = row.get("finishedAt")
    else:
        raise connection.DokployUnavailable()
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise connection.DokployUnavailable()
    try:
        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:
            raise ValueError("Timezone required")
        normalized_at = occurred_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except ValueError:
        raise connection.DokployUnavailable() from None
    # Deliberately no inferred commit, logs, error messages, title or environment.
    values = {
        "provider": "dokploy",
        "event_type": event_type,
        "occurred_at": normalized_at,
        "external_id": external_id,
        "outcome": outcome,
        "commit_sha": "",
    }
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    return {**values, "event_id": digest, "payload_digest": digest}


def _scope(service, actor, project_uid, connection_uid, resource_uid, *, lock=False):
    board = connection._board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        if not signal_app_allowed(db, "dokploy", lock=lock):
            raise connection.DokployUnavailable()
        conn = connection._connection(db, actor, connection_uid, lock=lock)
        connection._access(db, actor, board, conn)
        query = SqlBuilder.select.table(BoardAppBinding).where(
            BoardAppBinding.project_id == board.id,
            BoardAppBinding.app_key == "dokploy",
        )
        binding = db.exec(query.with_for_update() if lock else query).first()
        if (
            binding is None
            or binding.state not in {"enabled", "needs_attention"}
            or not {"signals.read", "deployments.read"}.issubset(binding.granted_capabilities)
        ):
            raise connection.DokployUnavailable()
        query = SqlBuilder.select.table(AppResourceBinding).where(
            AppResourceBinding.id == InfraHelper.convert_id(resource_uid),
            AppResourceBinding.board_binding_id == binding.id,
            AppResourceBinding.connection_id == conn.id,
            AppResourceBinding.resource_type.in_(("application", "compose")),
            AppResourceBinding.is_selected == True,  # noqa: E712
            AppResourceBinding.access_state == "granted",
        )
        resource = db.exec(query.with_for_update() if lock else query).first()
        if resource is None:
            raise connection.DokployUnavailable()
    return conn, binding.edit_revision(), resource


def refresh_deployments(
    service, actor, project_uid, connection_uid, resource_uid, expected_revision, expected_access_revision
):
    conn, binding_revision, resource = _scope(service, actor, project_uid, connection_uid, resource_uid)
    if connection._revision(conn) != expected_revision or resource.access_revision != expected_access_revision:
        raise connection.DokployConflict()
    base = connection.approved_instance(conn.instance_url)
    token, secret_revision = connection._credential(service, actor, conn.credential_reference)
    path = resource.resource_path
    if (
        len(path) != 3
        or path[0].get("type") != "project"
        or path[1].get("type") != "environment"
        or path[2].get("type") != resource.resource_type
        or path[2].get("id") != resource.external_resource_id
    ):
        raise connection.DokployUnavailable()
    # Recheck current provider hierarchy before reading the deployment endpoint.
    items = connection._discover_items(base, token, connection._id(path[0]["id"]), connection._id(path[1]["id"]))
    if not any(row["id"] == resource.external_resource_id and row["type"] == resource.resource_type for row in items):
        raise connection.DokployUnavailable()
    endpoint = "deployment.all" if resource.resource_type == "application" else "deployment.allByCompose"
    try:
        data, _ = read_json(
            base,
            "/api/" + endpoint,
            {"x-api-key": token, "Accept": "application/json"},
            {resource.resource_type + "Id": resource.external_resource_id},
        )
    except MetadataUnavailable:
        raise connection.DokployUnavailable() from None
    normalized = [
        normalize_deployment(row, resource.resource_type, resource.external_resource_id)
        for row in connection._rows(data)
    ]
    normalized.sort(key=lambda row: (row["occurred_at"], row["event_id"]), reverse=True)
    page = normalized[:25]
    with DbSession.atomic() as db:
        connection._current(service, actor, project_uid, conn, secret_revision)
        _, current_binding_revision, current = _scope(
            service, actor, project_uid, connection_uid, resource_uid, lock=True
        )
        if (
            current_binding_revision != binding_revision
            or current.access_revision != expected_access_revision
            or current.resource_path != path
        ):
            raise connection.DokployConflict()
        existing_by_id = (
            {
                row.event_id: row
                for row in db.exec(
                    SqlBuilder.select.table(AppSignal).where(
                        AppSignal.resource_id == current.id,
                        AppSignal.event_id.in_([values["event_id"] for values in page]),
                    )
                ).all()
            }
            if page
            else {}
        )
        inserted = 0
        for values in page:
            existing = existing_by_id.get(values["event_id"])
            if existing is None:
                existing = AppSignal(resource_id=current.id, **values)
                db.insert(existing)
                existing_by_id[values["event_id"]] = existing
                inserted += 1
            elif any(getattr(existing, key) != value for key, value in values.items()):
                raise connection.DokployConflict()
        current.health = "healthy"
        db.update(current)
        if inserted:
            db.after_commit(lambda: CardPublisher.app_signal_changed(project_uid))
    return {
        "resource_uid": resource_uid,
        "inserted": inserted,
        "items": [
            {key: values[key] for key in ("event_type", "occurred_at", "external_id", "outcome")} for values in page
        ],
        "truncated": len(normalized) > 25,
        "limit": 25,
    }
