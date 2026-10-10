"""GlitchTip metadata connections; raw diagnostics stay on its official MCP."""

import hashlib
import json
import re
from urllib.parse import urlsplit
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied, require_connection_access
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import AppSettingPublisher
from .MetadataTransport import MetadataUnavailable, approved_instance, read_json


class GlitchTipUnavailable(Exception):
    pass


class GlitchTipConflict(Exception):
    pass


def _board(service, actor, project_uid, *, revocation=False):
    board = service.workflow_stage._authorized_app_board(
        actor, project_uid, ProjectRoleAction.Update, lock=DbSession.has_active_transaction(), revocation=revocation
    )
    if board is None:
        raise GlitchTipUnavailable()
    return board


_instance = approved_instance


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Invalid GlitchTip resource slug")
    return value


def _revision(connection):
    return hashlib.sha256(
        json.dumps(
            {
                "id": int(connection.id),
                "owner": int(connection.owner_id),
                "ownership": connection.ownership,
                "organization_id": int(connection.organization_id) if connection.organization_id is not None else None,
                "app": connection.app_key,
                "instance": connection.instance_url,
                "credential": connection.credential_reference,
                "state": connection.state,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _metadata(connection):
    return {
        "connection_uid": connection.get_uid(),
        "instance_url": connection.instance_url,
        "state": connection.state,
        "revision": _revision(connection),
        "official_mcp_url": connection.instance_url + "/mcp",
    }


def _credential(service, actor, uri):
    if not isinstance(uri, str) or not re.fullmatch(r"secret://ref/[A-Za-z0-9]{1,11}", uri):
        raise ValueError("Use a canonical secret reference")
    metadata = service.secret_reference.get_metadata(actor, uri)
    token = service.secret_reference.resolve_for_runtime(
        actor, uri, source=SecretAuditSource("api", "glitchtip_connection")
    ).get_secret_value()
    # A DSN is an ingest URL, never an API bearer token. Never echo invalid material.
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,4096}", token):
        raise GlitchTipUnavailable()
    return token, metadata["revision"]


def _get(base, token, path, params=None):
    try:
        data, links = read_json(base, path, {"Authorization": "Bearer " + token, "Accept": "application/json"}, params)
    except MetadataUnavailable:
        raise GlitchTipUnavailable() from None
    cursor = None
    for link in links.values():
        if link.get("rel") == "next" and link.get("results") == "true":
            from urllib.parse import parse_qs

            values = parse_qs(urlsplit(link.get("url", "")).query).get("cursor", [])
            if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9:_-]{1,256}", values[0]):
                raise GlitchTipUnavailable()
            cursor = values[0]
    return data, cursor


def _fence(service, actor, project_uid, uri, secret_revision):
    board = _board(service, actor, project_uid)
    current = service.secret_reference._find(actor, uri, lock=DbSession.has_active_transaction()).metadata()
    if current["revision"] != secret_revision or current["state"] != "active":
        raise GlitchTipConflict()
    return board


def register_connection(service, actor, project_uid, instance_url, credential_reference):
    _board(service, actor, project_uid)
    base = _instance(instance_url)
    token, revision = _credential(service, actor, credential_reference)
    data, _ = _get(base, token, "/api/0/organizations/", {"limit": 1})
    if not isinstance(data, list) or len(data) > 1:
        raise GlitchTipUnavailable()
    with DbSession.atomic() as db:
        _fence(service, actor, project_uid, credential_reference, revision)
        connection = AppConnection(
            app_key="glitchtip",
            owner_id=actor.id,
            instance_url=base,
            credential_reference=credential_reference,
            state="connected",
        )
        db.insert(connection)
        service.secret_reference.audit_binding(
            actor, credential_reference, revision, source=SecretAuditSource("app_connection", connection.get_uid())
        )
        return _metadata(connection)


def _connection(db, actor, uid, *, lock=False, revocation=False):
    query = SqlBuilder.select.table(AppConnection).where(
        AppConnection.id == InfraHelper.convert_id(uid),
        AppConnection.owner_id == actor.id,
        AppConnection.app_key == "glitchtip",
    )
    row = db.exec(query.with_for_update() if lock else query).first()
    allowed_states = ("connected", "pending", "revoked", "disconnected") if revocation else ("connected",)
    if row is None or row.state not in allowed_states or (not revocation and not row.credential_reference):
        raise GlitchTipUnavailable()
    return row


def list_connections(service, actor, project_uid, after=None):
    _board(service, actor, project_uid, revocation=True)
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid connection cursor")
    with DbSession.use(readonly=False) as db:
        rows = db.exec(
            SqlBuilder.select.table(AppConnection)
            .where(
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "glitchtip",
                AppConnection.state.in_(["pending", "connected", "revoked", "disconnected"]),
                AppConnection.id > (InfraHelper.convert_id(after) if after else 0),
            )
            .order_by(AppConnection.id)
            .limit(26)
        ).all()
    return {
        "items": [_metadata(row) for row in rows[:25]],
        "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
    }


def _context(service, actor, project_uid, uid):
    board = _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = _connection(db, actor, uid)
        _access(db, actor, board, connection)
    base = _instance(connection.instance_url)
    token, secret_revision = _credential(service, actor, connection.credential_reference)
    return connection, base, token, secret_revision


def _current(service, actor, project_uid, connection, secret_revision):
    board = _fence(service, actor, project_uid, connection.credential_reference, secret_revision)
    with DbSession.use(readonly=False) as db:
        current = _connection(db, actor, connection.get_uid(), lock=DbSession.has_active_transaction())
        _access(db, actor, board, current)
        if _revision(current) != _revision(connection):
            raise GlitchTipConflict()
    _instance(current.instance_url)


def _access(db, actor, board, connection):
    try:
        require_connection_access(db, actor, board, connection)
    except AppGovernanceDenied:
        raise GlitchTipUnavailable() from None


def discover_resources(service, actor, project_uid, connection_uid, organization=None, cursor=None):
    if cursor is not None and not re.fullmatch(r"[A-Za-z0-9:_-]{1,256}", cursor):
        raise ValueError("Invalid resource cursor")
    if organization is not None:
        _slug(organization)
    connection, base, token, secret_revision = _context(service, actor, project_uid, connection_uid)
    path = "/api/0/organizations/" if organization is None else f"/api/0/organizations/{organization}/projects/"
    data, next_cursor = _get(base, token, path, {"limit": 25, **({"cursor": cursor} if cursor else {})})
    if not isinstance(data, list) or len(data) > 25:
        raise GlitchTipUnavailable()
    items = []
    for item in data:
        if not isinstance(item, dict) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(item.get("id", ""))):
            raise GlitchTipUnavailable()
        slug = _slug(item.get("slug"))
        name = item.get("name")
        if not isinstance(name, str) or len(name) > 200:
            raise GlitchTipUnavailable()
        if organization is not None and item.get("hasAccess") is not True:
            continue
        items.append({"id": str(item["id"]), "slug": slug, "name": name})
    _current(service, actor, project_uid, connection, secret_revision)
    return {"items": items, "next_cursor": next_cursor, "connection_revision": _revision(connection)}


def bind_project(
    service,
    actor,
    project_uid,
    connection_uid,
    organization,
    project_slug,
    expected_revision,
    expected_resource_revision=None,
):
    _slug(organization)
    _slug(project_slug)
    connection, base, token, secret_revision = _context(service, actor, project_uid, connection_uid)
    if _revision(connection) != expected_revision:
        raise GlitchTipConflict()
    data, _ = _get(base, token, f"/api/0/projects/{organization}/{project_slug}/")
    if (
        not isinstance(data, dict)
        or data.get("hasAccess") is not True
        or data.get("slug") != project_slug
        or not isinstance(data.get("organization"), dict)
        or data["organization"].get("slug") != organization
        or not re.fullmatch(r"[1-9][0-9]{0,19}", str(data.get("id", "")))
    ):
        raise GlitchTipUnavailable()
    external_id = str(data["id"])
    with DbSession.atomic() as db:
        # Serialize first binding creation with the board's existing parent lock.
        parent = _board(service, actor, project_uid)
        _current(service, actor, project_uid, connection, secret_revision)
        _connection(db, actor, connection_uid, lock=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == parent.id,
                BoardAppBinding.app_key == "glitchtip",
            )
            .with_for_update()
        ).first()
        if binding is None:
            binding = BoardAppBinding(project_id=parent.id, app_key="glitchtip")
            db.insert(binding)
        row = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == "project",
                AppResourceBinding.external_resource_id == external_id,
            )
            .with_for_update()
        ).first()
        path = [
            {"type": "organization", "id": organization},
            {"type": "project", "id": external_id, "slug": project_slug},
        ]
        if row is not None and row.access_revision != expected_resource_revision:
            raise GlitchTipConflict()
        if row is None and expected_resource_revision is not None:
            raise GlitchTipConflict()
        if row is None:
            row = AppResourceBinding(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="project",
                external_resource_id=external_id,
            )
            db.insert(row)
        row.resource_path, row.is_selected, row.access_state, row.health = path, True, "granted", "healthy"
        row.access_revision += 1
        db.update(row)
        service.secret_reference.audit_binding(
            actor,
            connection.credential_reference,
            secret_revision,
            source=SecretAuditSource("app_connection", connection.get_uid()),
        )
        # Never enable workflow transitions or grant unrelated signal capabilities.
        return {
            "resource_uid": row.get_uid(),
            "project_id": external_id,
            "path": path,
            "access_state": row.access_state,
            "access_revision": row.access_revision,
        }


def selected_projects(service, actor, project_uid, connection_uid, after=None):
    board = _board(service, actor, project_uid, revocation=True)
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid resource cursor")
    with DbSession.use(readonly=False) as db:
        connection = _connection(db, actor, connection_uid, revocation=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "glitchtip",
            )
        ).first()
        rows = (
            []
            if binding is None
            else db.exec(
                SqlBuilder.select.table(AppResourceBinding)
                .where(
                    AppResourceBinding.board_binding_id == binding.id,
                    AppResourceBinding.connection_id == connection.id,
                    AppResourceBinding.resource_type == "project",
                    AppResourceBinding.id > (InfraHelper.convert_id(after) if after else 0),
                )
                .order_by(AppResourceBinding.id)
                .limit(26)
            ).all()
        )
        return {
            "binding": None
            if binding is None
            else {
                "uid": binding.get_uid(),
                "revision": binding.edit_revision(),
                "state": binding.state,
                "granted_capabilities": list(binding.granted_capabilities),
            },
            "items": [
                {
                    "resource_uid": row.get_uid(),
                    "project_id": row.external_resource_id,
                    "path": row.resource_path,
                    "access_revision": row.access_revision,
                    "access_state": row.access_state,
                    "health": row.health,
                    "selected": row.is_selected,
                }
                for row in rows[:25]
            ],
            "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
        }


def remove_project(service, actor, project_uid, connection_uid, resource_uid, expected_revision):
    with DbSession.atomic() as db:
        board = _board(service, actor, project_uid, revocation=True)
        connection = _connection(db, actor, connection_uid, lock=True, revocation=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "glitchtip",
            )
            .with_for_update()
        ).first()
        if binding is None:
            raise GlitchTipUnavailable()
        row = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.id == InfraHelper.convert_id(resource_uid),
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == "project",
            )
            .with_for_update()
        ).first()
        if row is None:
            raise GlitchTipUnavailable()
        if row.access_revision != expected_revision:
            raise GlitchTipConflict()
        if row.is_selected:
            row.is_selected = False
            row.access_revision += 1
            db.update(row)
            db.after_commit(AppSettingPublisher.apps_changed)
        return {"resource_uid": row.get_uid(), "selected": False, "access_revision": row.access_revision}


def disconnect(service, actor, project_uid, connection_uid, expected_revision):
    _board(service, actor, project_uid, revocation=True)
    with DbSession.atomic() as db:
        _board(service, actor, project_uid, revocation=True)
        connection = _connection(db, actor, connection_uid, lock=True, revocation=True)
        if _revision(connection) != expected_revision:
            raise GlitchTipConflict()
        if connection.state == "disconnected":
            return _metadata(connection)
        connection.state = "disconnected"
        db.update(connection)
        # Preserve selected resources, cards and workflow configuration. The
        # shared credential may serve another connection and is not revoked here.
        db.exec(
            SqlBuilder.update.table(AppResourceBinding)
            .where(
                AppResourceBinding.connection_id == connection.id,
            )
            .values(
                access_state="revoked", health="unavailable", access_revision=AppResourceBinding.access_revision + 1
            )
        )
        db.after_commit(AppSettingPublisher.apps_changed)
        return _metadata(connection)


def disable_read_access(service, actor, project_uid, connection_uid, expected_revision, expected_binding_revision):
    """Revoke board read grants without requiring a live credential or provider."""
    with DbSession.atomic() as db:
        board = _board(service, actor, project_uid, revocation=True)
        connection = _connection(db, actor, connection_uid, lock=True, revocation=True)
        if _revision(connection) != expected_revision:
            raise GlitchTipConflict()
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(
            BoardAppBinding.project_id == board.id, BoardAppBinding.app_key == "glitchtip",
        ).with_for_update()).first()
        if binding is None:
            raise GlitchTipUnavailable()
        if binding.edit_revision() != expected_binding_revision:
            raise GlitchTipConflict()
        binding.granted_capabilities = [grant for grant in binding.granted_capabilities if grant not in {"resources.read", "signals.read"}]
        if not binding.granted_capabilities:
            binding.state = "disabled"
        db.update(binding)
        if binding.edit_revision() != expected_binding_revision:
            db.after_commit(AppSettingPublisher.apps_changed)
        return {"uid": binding.get_uid(), "revision": binding.edit_revision(), "state": binding.state,
                "granted_capabilities": list(binding.granted_capabilities)}


def enable_read_access(service, actor, project_uid, connection_uid, expected_revision, expected_binding_revision):
    """Explicit board read consent; no provider writes or workflow authority."""
    with DbSession.atomic() as db:
        board = _board(service, actor, project_uid)
        conn = _connection(db, actor, connection_uid, lock=True)
        if _revision(conn) != expected_revision:
            raise GlitchTipConflict()
        _instance(conn.instance_url)
        _, secret_revision = _credential(service, actor, conn.credential_reference)
        _current(service, actor, project_uid, conn, secret_revision)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "glitchtip",
            )
            .with_for_update()
        ).first()
        if binding is None:
            raise GlitchTipUnavailable()
        if binding.edit_revision() != expected_binding_revision:
            raise GlitchTipConflict()
        selected = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == conn.id,
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.access_state == "granted",
                AppResourceBinding.resource_type == "project",
            )
            .limit(1)
        ).first()
        if selected is None:
            raise GlitchTipUnavailable()
        binding.state = "enabled"
        binding.granted_capabilities = list(dict.fromkeys([*binding.granted_capabilities, "resources.read", "signals.read"]))
        db.update(binding)
        return {
            "uid": binding.get_uid(),
            "revision": binding.edit_revision(),
            "state": binding.state,
            "granted_capabilities": list(binding.granted_capabilities),
        }
