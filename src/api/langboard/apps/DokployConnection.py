"""Dokploy metadata onboarding; provider writes and deployment bodies stay external."""

import hashlib
import json
import re
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from .MetadataTransport import MetadataUnavailable, approved_instance, read_json


class DokployUnavailable(Exception):
    pass


class DokployConflict(Exception):
    pass


def _board(service, actor, project_uid):
    board = service.workflow_stage._authorized_app_board(
        actor, project_uid, ProjectRoleAction.Update, lock=DbSession.has_active_transaction()
    )
    if board is None:
        raise DokployUnavailable()
    return board


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Invalid Dokploy resource identifier")
    return value


def _revision(connection):
    return hashlib.sha256(
        json.dumps(
            {
                "id": int(connection.id),
                "owner": int(connection.owner_id),
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
    }


def _credential(service, actor, uri):
    if not isinstance(uri, str) or not re.fullmatch(r"secret://ref/[A-Za-z0-9]{1,11}", uri):
        raise ValueError("Use a canonical secret reference")
    metadata = service.secret_reference.get_metadata(actor, uri)
    token = service.secret_reference.resolve_for_runtime(
        actor, uri, source=SecretAuditSource("api", "dokploy_connection")
    ).get_secret_value()
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,4096}", token):
        raise DokployUnavailable()
    return token, metadata["revision"]


def _get(base, token, endpoint, params=None):
    if endpoint not in {"project.all", "environment.byProjectId", "environment.one"}:
        raise ValueError("Unsupported metadata endpoint")
    try:
        data, _ = read_json(base, "/api/" + endpoint, {"x-api-key": token, "Accept": "application/json"}, params)
    except MetadataUnavailable:
        raise DokployUnavailable() from None
    return data


def _fence(service, actor, project_uid, uri, revision):
    _board(service, actor, project_uid)
    current = service.secret_reference._find(actor, uri, lock=DbSession.has_active_transaction()).metadata()
    if current["revision"] != revision or current["state"] != "active":
        raise DokployConflict()


def _connection(db, actor, uid, *, lock=False):
    _id(uid)
    query = SqlBuilder.select.table(AppConnection).where(
        AppConnection.id == InfraHelper.convert_id(uid),
        AppConnection.owner_id == actor.id,
        AppConnection.app_key == "dokploy",
    )
    row = db.exec(query.with_for_update() if lock else query).first()
    if row is None or row.state != "connected" or not row.credential_reference:
        raise DokployUnavailable()
    return row


def _context(service, actor, project_uid, uid):
    _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = _connection(db, actor, uid)
    base = approved_instance(connection.instance_url)
    token, revision = _credential(service, actor, connection.credential_reference)
    return connection, base, token, revision


def _current(service, actor, project_uid, connection, revision):
    _fence(service, actor, project_uid, connection.credential_reference, revision)
    with DbSession.use(readonly=False) as db:
        current = _connection(db, actor, connection.get_uid(), lock=DbSession.has_active_transaction())
        if _revision(current) != _revision(connection):
            raise DokployConflict()
    approved_instance(current.instance_url)


def _item(row, kind):
    if not isinstance(row, dict):
        raise DokployUnavailable()
    try:
        uid = _id(row.get(kind + "Id"))
    except ValueError:
        raise DokployUnavailable() from None
    name = row.get("name")
    if not isinstance(name, str) or not name or len(name) > 200:
        raise DokployUnavailable()
    return {"id": uid, "type": kind, "name": name}


def _rows(value):
    # These official endpoints have no pagination. Fail explicitly on oversized
    # inventories rather than inventing provider cursors or silently dropping rows.
    if not isinstance(value, list) or len(value) > 250:
        raise DokployUnavailable()
    return value


def register_connection(service, actor, project_uid, instance_url, credential_reference):
    _board(service, actor, project_uid)
    base = approved_instance(instance_url)
    token, revision = _credential(service, actor, credential_reference)
    for row in _rows(_get(base, token, "project.all")):
        _item(row, "project")
    with DbSession.atomic() as db:
        _fence(service, actor, project_uid, credential_reference, revision)
        # Recheck deployment policy after external I/O, before persisting.
        approved_instance(base)
        connection = AppConnection(
            app_key="dokploy",
            owner_id=actor.id,
            instance_url=base,
            credential_reference=credential_reference,
            state="connected",
        )
        db.insert(connection)
        return _metadata(connection)


def list_connections(service, actor, project_uid, after=None):
    _board(service, actor, project_uid)
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid connection cursor")
    with DbSession.use(readonly=False) as db:
        rows = db.exec(
            SqlBuilder.select.table(AppConnection)
            .where(
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "dokploy",
                AppConnection.state == "connected",
                AppConnection.id > (InfraHelper.convert_id(after) if after else 0),
            )
            .order_by(AppConnection.id)
            .limit(26)
        ).all()
    return {
        "items": [_metadata(row) for row in rows[:25]],
        "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
    }


def discover_resources(service, actor, project_uid, connection_uid, external_project_id=None, environment_id=None):
    if external_project_id is not None:
        _id(external_project_id)
    if environment_id is not None:
        _id(environment_id)
        if external_project_id is None:
            raise ValueError("Project required for environment discovery")
    connection, base, token, revision = _context(service, actor, project_uid, connection_uid)
    items = _discover_items(base, token, external_project_id, environment_id)
    _current(service, actor, project_uid, connection, revision)
    return {"items": items, "next_cursor": None, "connection_revision": _revision(connection)}


def _discover_items(base, token, external_project_id, environment_id):
    if external_project_id is None:
        items = [_item(row, "project") for row in _rows(_get(base, token, "project.all"))]
    else:
        environments = _rows(_get(base, token, "environment.byProjectId", {"projectId": external_project_id}))
        if environment_id is None:
            items = [_item(row, "environment") for row in environments]
        else:
            # Require the environment in the requested project's authorized list.
            if environment_id not in {_item(row, "environment")["id"] for row in environments}:
                raise DokployUnavailable()
            items = _environment_resources(base, token, external_project_id, environment_id)
    return items


def _environment_resources(base, token, external_project_id, environment_id):
    """Caller verified project membership within this same operation."""
    data = _get(base, token, "environment.one", {"environmentId": environment_id})
    if _item(data, "environment")["id"] != environment_id or data.get("projectId") != external_project_id:
        raise DokployUnavailable()
    items = [
        _item(row, kind)
        for key, kind in (("applications", "application"), ("compose", "compose"))
        for row in _rows(data.get(key, []))
    ]
    if len(items) > 250:
        raise DokployUnavailable()
    return items


def _resource_metadata(row):
    return {
        "resource_uid": row.get_uid(),
        "type": row.resource_type,
        "external_id": row.external_resource_id,
        "path": row.resource_path,
        "selected": row.is_selected,
        "access_state": row.access_state,
        "health": row.health,
        "access_revision": row.access_revision,
    }


def bind_resource(
    service,
    actor,
    project_uid,
    connection_uid,
    resource_type,
    external_id,
    external_project_id,
    environment_id,
    expected_revision,
    expected_resource_revision=None,
):
    """Select a provider-verified resource in one board, without granting writes."""
    if resource_type not in {"project", "environment", "application", "compose"}:
        raise ValueError("Unsupported Dokploy resource type")
    _id(external_id)
    if resource_type != "project":
        _id(external_project_id)
    if resource_type in {"application", "compose"}:
        _id(environment_id)
    if resource_type == "project" and (external_project_id is not None or environment_id is not None):
        raise ValueError("Project selection has no parent")
    if resource_type == "environment" and environment_id is not None:
        raise ValueError("Environment selection takes its parent project only")
    connection, base, token, secret_revision = _context(service, actor, project_uid, connection_uid)
    if _revision(connection) != expected_revision:
        raise DokployConflict()
    # Read the provider's visible hierarchy, never trust client-supplied names.
    parent_project = external_id if resource_type == "project" else external_project_id
    projects = _discover_items(base, token, None, None)
    project = next((row for row in projects if row["id"] == parent_project), None)
    if project is None:
        raise DokployUnavailable()
    path = [project]
    if resource_type != "project":
        environments = _discover_items(base, token, parent_project, None)
        parent_env = external_id if resource_type == "environment" else environment_id
        environment = next((row for row in environments if row["id"] == parent_env), None)
        if environment is None:
            raise DokployUnavailable()
        path.append(environment)
        if resource_type in {"application", "compose"}:
            items = _environment_resources(base, token, parent_project, parent_env)
            item = next((row for row in items if row["id"] == external_id and row["type"] == resource_type), None)
            if item is None:
                raise DokployUnavailable()
            path.append(item)
    with DbSession.atomic() as db:
        parent = _board(service, actor, project_uid)
        _current(service, actor, project_uid, connection, secret_revision)
        _connection(db, actor, connection_uid, lock=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == parent.id,
                BoardAppBinding.app_key == "dokploy",
            )
            .with_for_update()
        ).first()
        if binding is None:
            binding = BoardAppBinding(project_id=parent.id, app_key="dokploy")
            db.insert(binding)
        row = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == resource_type,
                AppResourceBinding.external_resource_id == external_id,
            )
            .with_for_update()
        ).first()
        if row is not None and row.access_revision != expected_resource_revision:
            raise DokployConflict()
        if row is None and expected_resource_revision is not None:
            raise DokployConflict()
        if row is None:
            row = AppResourceBinding(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type=resource_type,
                external_resource_id=external_id,
            )
            db.insert(row)
        row.resource_path, row.is_selected, row.access_state, row.health = path, True, "granted", "healthy"
        row.access_revision += 1
        db.update(row)
        # Selection is independent from workflow/signal capability activation.
        return _resource_metadata(row)


def selected_resources(service, actor, project_uid, connection_uid, after=None):
    board = _board(service, actor, project_uid)
    if after is not None and not re.fullmatch(r"[A-Za-z0-9]{1,11}", after):
        raise ValueError("Invalid resource cursor")
    with DbSession.use(readonly=False) as db:
        connection = _connection(db, actor, connection_uid)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "dokploy",
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
                    AppResourceBinding.id > (InfraHelper.convert_id(after) if after else 0),
                )
                .order_by(AppResourceBinding.id)
                .limit(26)
            ).all()
        )
        return {
            "items": [_resource_metadata(row) for row in rows[:25]],
            "next_cursor": rows[24].get_uid() if len(rows) > 25 else None,
            "binding": None
            if binding is None
            else {
                "uid": binding.get_uid(),
                "revision": binding.edit_revision(),
                "state": binding.state,
                "granted_capabilities": list(binding.granted_capabilities),
            },
        }


def enable_read_access(service, actor, project_uid, connection_uid, expected_revision, expected_binding_revision):
    """Explicit board read consent; no provider writes or workflow authority."""
    with DbSession.atomic() as db:
        board = _board(service, actor, project_uid)
        conn = _connection(db, actor, connection_uid, lock=True)
        if _revision(conn) != expected_revision:
            raise DokployConflict()
        approved_instance(conn.instance_url)
        _, secret_revision = _credential(service, actor, conn.credential_reference)
        _current(service, actor, project_uid, conn, secret_revision)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "dokploy",
            )
            .with_for_update()
        ).first()
        if binding is None:
            raise DokployUnavailable()
        if binding.edit_revision() != expected_binding_revision:
            raise DokployConflict()
        selected = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == conn.id,
                AppResourceBinding.is_selected == True,  # noqa: E712
                AppResourceBinding.access_state == "granted",
                AppResourceBinding.resource_type.in_(("application", "compose")),
            )
            .limit(1)
        ).first()
        if selected is None:
            raise DokployUnavailable()
        binding.state = "enabled"
        binding.granted_capabilities = ["resources.read", "signals.read", "deployments.read"]
        binding.stage_transitions_enabled = False
        db.update(binding)
        return {
            "uid": binding.get_uid(),
            "revision": binding.edit_revision(),
            "state": binding.state,
            "granted_capabilities": list(binding.granted_capabilities),
        }


def remove_resource(service, actor, project_uid, connection_uid, resource_uid, expected_revision):
    with DbSession.atomic() as db:
        board = _board(service, actor, project_uid)
        connection = _connection(db, actor, connection_uid, lock=True)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "dokploy",
            )
            .with_for_update()
        ).first()
        if binding is None:
            raise DokployUnavailable()
        row = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.id == InfraHelper.convert_id(resource_uid),
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == connection.id,
            )
            .with_for_update()
        ).first()
        if row is None:
            raise DokployUnavailable()
        if row.access_revision != expected_revision:
            raise DokployConflict()
        row.is_selected = False
        row.access_revision += 1
        db.update(row)
        return _resource_metadata(row)


def disconnect(service, actor, project_uid, connection_uid, expected_revision):
    with DbSession.atomic() as db:
        _board(service, actor, project_uid)
        connection = _connection(db, actor, connection_uid, lock=True)
        if _revision(connection) != expected_revision:
            raise DokployConflict()
        connection.state = "disconnected"
        db.update(connection)
        db.exec(
            SqlBuilder.update.table(AppResourceBinding)
            .where(
                AppResourceBinding.connection_id == connection.id,
            )
            .values(
                access_state="revoked", health="unavailable", access_revision=AppResourceBinding.access_revision + 1
            )
        )
        # Connection is shared across boards. Preserve selections and each board's
        # configuration; invalidate this connection's resources everywhere.
        # Its SecretReference may serve another connection and remains untouched.
        return _metadata(connection)
