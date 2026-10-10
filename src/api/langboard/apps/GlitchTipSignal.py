"""Explicit GlitchTip status observations, never inferred lifecycle occurrences.

GlitchTip v6.2.6 issue metadata exposes status and firstSeen/lastSeen, but no
resolution, reopening or regression occurrence time. occurred_at is the server's
UTC observation time. Omitted issues provide no evidence of resolution.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppResourceBinding, AppSignal, BoardAppBinding
from langboard_shared.domain.services.AppRegistry import signal_app_allowed
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardPublisher
from sqlalchemy import func, select
from . import GlitchTipConnection as connection


def _numeric_id(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or not re.fullmatch(r"[1-9][0-9]{0,19}", str(value))
    ):
        raise connection.GlitchTipUnavailable()
    return str(value)


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise connection.GlitchTipUnavailable()
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Timezone required")
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise connection.GlitchTipUnavailable() from None


def normalize_issue(row, project_id, project_slug, observed_at):
    if not isinstance(row, dict) or not isinstance(row.get("project"), dict):
        raise connection.GlitchTipUnavailable()
    project = row["project"]
    if _numeric_id(project.get("id")) != project_id or project.get("slug") != project_slug:
        raise connection.GlitchTipUnavailable()
    status = row.get("status")
    if not isinstance(status, str) or status not in {"unresolved", "resolved", "ignored"}:
        raise connection.GlitchTipUnavailable()
    first, last = _timestamp(row.get("firstSeen")), _timestamp(row.get("lastSeen"))
    if first > last or last > observed_at:
        raise connection.GlitchTipUnavailable()
    # Hash only whitelisted metadata. Raw diagnostic fields never leave the provider.
    metadata = {
        "id": _numeric_id(row.get("id")),
        "project_id": project_id,
        "project_slug": project_slug,
        "status": status,
        "firstSeen": first.isoformat(timespec="microseconds"),
        "lastSeen": last.isoformat(timespec="microseconds"),
    }
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return {
        "provider": "glitchtip",
        "event_type": "issue.status_observed",
        "external_id": metadata["id"],
        "outcome": status,
        "commit_sha": "",
        "payload_digest": digest,
        "occurred_at": observed_at.isoformat(timespec="microseconds"),
    }


def _scope(service, actor, project_uid, connection_uid, resource_uid, *, lock=False):
    board = connection._board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        if not signal_app_allowed(db, "glitchtip", lock=lock):
            raise connection.GlitchTipUnavailable()
        conn = connection._connection(db, actor, connection_uid, lock=lock)
        connection._access(db, actor, board, conn)
        query = SqlBuilder.select.table(BoardAppBinding).where(
            BoardAppBinding.project_id == board.id,
            BoardAppBinding.app_key == "glitchtip",
        )
        binding = db.exec(query.with_for_update() if lock else query).first()
        if (
            binding is None
            or binding.state not in {"enabled", "needs_attention"}
            or not {"resources.read", "signals.read"}.issubset(binding.granted_capabilities)
        ):
            raise connection.GlitchTipUnavailable()
        query = SqlBuilder.select.table(AppResourceBinding).where(
            AppResourceBinding.id == InfraHelper.convert_id(resource_uid),
            AppResourceBinding.board_binding_id == binding.id,
            AppResourceBinding.connection_id == conn.id,
            AppResourceBinding.resource_type == "project",
            AppResourceBinding.is_selected == True,  # noqa: E712
            AppResourceBinding.access_state == "granted",
        )
        resource = db.exec(query.with_for_update() if lock else query).first()
        if resource is None:
            raise connection.GlitchTipUnavailable()
    return conn, binding.edit_revision(), resource


def _watermark(db, resource_id):
    row = db.exec(
        SqlBuilder.select.table(AppSignal)
        .where(
            AppSignal.resource_id == resource_id,
            AppSignal.provider == "glitchtip",
        )
        .order_by(AppSignal.id.desc())
        .limit(1)
    ).first()
    return row.id if row else None


def refresh_issues(
    service,
    actor,
    project_uid,
    connection_uid,
    resource_uid,
    expected_connection_revision,
    expected_access_revision,
    cursor=None,
):
    if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,256}", cursor)):
        raise ValueError("Invalid issue cursor")
    conn, binding_revision, resource = _scope(service, actor, project_uid, connection_uid, resource_uid)
    if (
        connection._revision(conn) != expected_connection_revision
        or resource.access_revision != expected_access_revision
    ):
        raise connection.GlitchTipConflict()
    base = connection._instance(conn.instance_url)
    token, secret_revision = connection._credential(service, actor, conn.credential_reference)
    path = resource.resource_path
    if (
        not isinstance(path, list)
        or len(path) != 2
        or any(not isinstance(p, dict) for p in path)
        or path[0].get("type") != "organization"
        or path[1].get("type") != "project"
        or path[1].get("id") != resource.external_resource_id
    ):
        raise connection.GlitchTipUnavailable()
    organization, slug = connection._slug(path[0].get("id")), connection._slug(path[1].get("slug"))
    project_id = _numeric_id(resource.external_resource_id)
    with DbSession.use(readonly=False) as db:
        watermark = _watermark(db, resource.id)
    endpoint = f"/api/0/projects/{organization}/{slug}/"
    detail, _ = connection._get(base, token, endpoint)
    if (
        not isinstance(detail, dict)
        or detail.get("hasAccess") is not True
        or _numeric_id(detail.get("id")) != project_id
        or detail.get("slug") != slug
        or not isinstance(detail.get("organization"), dict)
        or detail["organization"].get("slug") != organization
    ):
        raise connection.GlitchTipUnavailable()
    data, next_cursor = connection._get(
        base,
        token,
        endpoint + "issues/",
        {
            "limit": 25,
            "sort": "-last_seen",
            **({"cursor": cursor} if cursor else {}),
        },
    )
    if not isinstance(data, list) or len(data) > 25:
        raise connection.GlitchTipUnavailable()
    observed_at = datetime.now(timezone.utc)
    page = {}
    for row in data:
        values = normalize_issue(row, project_id, slug, observed_at)
        prior = page.get(values["external_id"])
        if prior is not None and prior != values:
            raise connection.GlitchTipUnavailable()
        page[values["external_id"]] = values
    with DbSession.atomic() as db:
        connection._current(service, actor, project_uid, conn, secret_revision)
        _, current_revision, current = _scope(service, actor, project_uid, connection_uid, resource_uid, lock=True)
        if (
            current_revision != binding_revision
            or current.access_revision != expected_access_revision
            or current.resource_path != path
            or _watermark(db, current.id) != watermark
        ):
            raise connection.GlitchTipConflict()
        latest_ids = (
            select(func.max(AppSignal.id))
            .where(
                AppSignal.resource_id == current.id,
                AppSignal.provider == "glitchtip",
                AppSignal.external_id.in_(list(page)),
            )
            .group_by(AppSignal.external_id)
        )
        latest = (
            {
                row.external_id: row
                for row in db.exec(SqlBuilder.select.table(AppSignal).where(AppSignal.id.in_(latest_ids))).all()
            }
            if page
            else {}
        )
        accepted = 0
        items = []
        for issue_id, values in page.items():
            prior = latest.get(issue_id)
            if prior is None or prior.payload_digest != values["payload_digest"]:
                # Chain to the previous observation so status cycles retain every transition.
                event_id = hashlib.sha256(
                    ((prior.event_id if prior else "") + values["payload_digest"]).encode()
                ).hexdigest()
                stored = AppSignal(resource_id=current.id, event_id=event_id, **values)
                db.insert(stored)
                accepted += 1
            else:
                stored = prior
            items.append({key: getattr(stored, key) for key in ("event_type", "occurred_at", "external_id", "outcome")})
        current.health = "healthy"
        db.update(current)
        if accepted:
            db.after_commit(lambda: CardPublisher.app_signal_changed(project_uid))
    return {
        "resource_uid": resource_uid,
        "accepted_count": accepted,
        "next_cursor": next_cursor,
        "limit": 25,
        "semantics": "status_observation",
        "items": items,
    }
