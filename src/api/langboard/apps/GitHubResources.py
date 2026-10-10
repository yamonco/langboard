"""Revision-checked repository deltas preserve unrelated board resource selections."""

import hashlib
import json
import re
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding, Project, User
from langboard_shared.domain.services import DomainService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import CardPublisher
from .GitHubAuthorization import require_installation_proof
from .GitHubInstallation import connection_revision, inspect_installation
from .GitHubManifest import GitHubManifestUnavailable, _board


class GitHubNoSelectedRepositories(ValueError):
    pass


class GitHubResourceConflict(Exception):
    pass


def resource_snapshot(db, binding):
    rows = (
        []
        if binding is None
        else db.exec(
            SqlBuilder.select.table(AppResourceBinding).where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.resource_type == "repository",
            )
        ).all()
    )
    return _snapshot_rows(rows)


def _snapshot_rows(rows):
    items = sorted(
        [
            {
                "uid": row.get_uid(),
                "connection_uid": InfraHelper.convert_uid(row.connection_id),
                "repository_id": row.external_resource_id,
                "selected": row.is_selected,
                "path": row.resource_path,
                "access_state": row.access_state,
                "access_revision": row.access_revision,
                "health": row.health,
            }
            for row in rows
        ],
        key=lambda item: item["uid"],
    )
    revision = hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"items": items, "revision": revision}


def _receipt_page(db, binding, connection_id, installation_scope, repository_scope, after, *, lock=False):
    """Only the receipt's current selected page, including one continuation row."""
    if binding is None:
        raise GitHubNoSelectedRepositories("No selected repositories to refresh")
    query = SqlBuilder.select.table(AppResourceBinding).where(
        AppResourceBinding.board_binding_id == binding.id,
        AppResourceBinding.connection_id == connection_id,
        AppResourceBinding.resource_type == "repository",
        AppResourceBinding.is_selected == True,  # noqa: E712
        AppResourceBinding.resource_path[0]["id"].as_string() == installation_scope[0],
        AppResourceBinding.resource_path[1]["id"].as_string() == installation_scope[1],
    )
    if repository_scope is not None:
        query = query.where(AppResourceBinding.external_resource_id.in_(repository_scope))
    if after is not None:
        if not isinstance(after, str) or not re.fullmatch(r"[0-9A-Za-z]{11}", after):
            raise ValueError("Invalid resource cursor")
        cursor_id = InfraHelper.convert_id(after)
        if db.exec(query.where(AppResourceBinding.id == cursor_id).limit(1)).first() is None:
            raise ValueError("Invalid resource cursor")
        query = query.where(AppResourceBinding.id > cursor_id)
    query = query.order_by(AppResourceBinding.id).limit(26)
    if lock:
        query = query.with_for_update()
    rows = db.exec(query).all()
    if not rows:
        raise GitHubNoSelectedRepositories("No selected repositories to refresh")
    items = sorted(_snapshot_rows(rows[:25])["items"], key=lambda item: InfraHelper.convert_id(item["uid"]))
    return _snapshot_rows(rows), rows[24].get_uid() if len(rows) > 25 else None, items


def get_resources(service: DomainService, actor: User, project_uid: str) -> dict:
    # Retained selection state is needed to obtain the revision for removal.
    # This does not authorize provider discovery or new selections.
    board = _board(service, actor, project_uid, revocation=True)
    with DbSession.use(readonly=False) as db:
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "github",
            )
        ).first()
        return resource_snapshot(db, binding)


def update_resources(
    service: DomainService,
    actor: User,
    project_uid: str,
    connection_uid: str,
    installation_id: int,
    account_id: int,
    add: tuple[int, ...],
    remove: tuple[int, ...],
    expected_revision: str,
    installation_proof: str | None = None,
) -> dict:
    if not add and not remove or len(add) > 25 or len(remove) > 25 or set(add) & set(remove):
        raise ValueError("Invalid repository delta")
    if (
        any(type(uid) is not int or uid <= 0 for uid in add + remove)
        or len(set(add)) != len(add)
        or len(set(remove)) != len(remove)
    ):
        raise ValueError("Invalid repository identifiers")
    if add:
        require_installation_proof(actor, project_uid, connection_uid, installation_id, account_id, installation_proof)
    verified = (
        inspect_installation(
            service, actor, project_uid, connection_uid, installation_id, account_id, repository_ids=add
        )
        if add
        else None
    )
    with DbSession.atomic() as db:
        board = db.exec(
            SqlBuilder.select.table(Project).where(Project.id == InfraHelper.convert_id(project_uid)).with_for_update()
        ).first()
        if board is None:
            raise GitHubManifestUnavailable()
        _board(service, actor, project_uid, revocation=not add)
        connection = db.exec(
            SqlBuilder.select.table(AppConnection)
            .where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.app_key == "github",
                AppConnection.owner_id == actor.id,
            )
            .with_for_update()
        ).first()
        allowed_states = {"pending", "connected"} if add else {"pending", "connected", "revoked", "disconnected"}
        if connection is None or connection.state not in allowed_states:
            raise GitHubManifestUnavailable()
        if add:
            require_installation_proof(
                actor,
                project_uid,
                connection_uid,
                installation_id,
                account_id,
                installation_proof,
                connection_revision(connection),
            )
        if verified and connection_revision(connection) != verified["connection_revision"]:
            raise GitHubResourceConflict()
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding)
            .where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "github",
            )
            .with_for_update()
        ).first()
        if resource_snapshot(db, binding)["revision"] != expected_revision:
            raise GitHubResourceConflict()
        if binding is None:
            if remove:
                raise ValueError("Repository is not bound")
            binding = BoardAppBinding(project_id=board.id, app_key="github")
            db.insert(binding)
        rows = db.exec(
            SqlBuilder.select.table(AppResourceBinding)
            .where(
                AppResourceBinding.board_binding_id == binding.id,
                AppResourceBinding.connection_id == connection.id,
                AppResourceBinding.resource_type == "repository",
            )
            .with_for_update()
        ).all()
        by_id = {int(row.external_resource_id): row for row in rows}
        for uid in remove:
            row = by_id.get(uid)
            if row is None:
                raise ValueError("Repository is not bound to this connection")
            row.is_selected = False
            db.update(row)
        for item in verified["repositories"] if verified else []:
            uid = item["id"]
            row = by_id.get(uid)
            path = [
                {"type": "installation", "id": str(installation_id)},
                {"type": "account", "id": str(account_id)},
                {"type": "repository", "id": str(uid), "name": item["name"]},
            ]
            if row and row.resource_path and row.resource_path[0].get("id") != str(installation_id):
                raise ValueError("Repository already uses another installation")
            if row is None:
                row = AppResourceBinding(
                    board_binding_id=binding.id,
                    connection_id=connection.id,
                    resource_type="repository",
                    external_resource_id=str(uid),
                    resource_path=path,
                    access_state="granted",
                    health="unknown",
                )
                db.insert(row)
            else:
                row.resource_path, row.is_selected, row.access_state = path, True, "granted"
                db.update(row)
        # Resource access does not authorize workflow actions, webhook processing,
        # or activation. Existing state/grants/mapping and shared Connection remain.
        db.after_commit(lambda: CardPublisher.app_signal_changed(project_uid))
        return resource_snapshot(db, binding)


def refresh_resources(
    service,
    actor,
    project_uid,
    connection_uid,
    expected_revision,
    after=None,
    *,
    installation_scope=None,
    repository_scope=None,
    expected_connection_revision=None,
    receipt_page=False,
):
    """Explicit bounded health refresh; unavailable evidence never means uninstall."""
    _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = db.exec(
            SqlBuilder.select.table(AppConnection).where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "github",
            )
        ).first()
        if connection is None or connection.state not in {"pending", "connected"}:
            raise GitHubManifestUnavailable()
        revision = connection_revision(connection)
        if expected_connection_revision is not None and revision != expected_connection_revision:
            raise GitHubResourceConflict()
        board = _board(service, actor, project_uid)
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == board.id,
                BoardAppBinding.app_key == "github",
            )
        ).first()
        if receipt_page:
            if installation_scope is None or expected_connection_revision is None:
                raise ValueError("Receipt page requires installation and connection revision")
            snapshot, next_cursor, rows = _receipt_page(
                db, binding, connection.id, installation_scope, repository_scope, after
            )
            expected_revision = snapshot["revision"]
        else:
            snapshot = resource_snapshot(db, binding)
            if snapshot["revision"] != expected_revision:
                raise GitHubResourceConflict()
            rows = [item for item in snapshot["items"] if item["connection_uid"] == connection_uid and item["selected"]]
    if not receipt_page and installation_scope is not None:
        rows = [item for item in rows if tuple(part.get("id") for part in item["path"][:2]) == installation_scope]
    if not receipt_page and repository_scope is not None:
        rows = [item for item in rows if item["repository_id"] in repository_scope]
    if not receipt_page and after is not None:
        if not isinstance(after, str) or len(after) > 11 or not any(item["uid"] == after for item in rows):
            raise ValueError("Invalid resource cursor")
        rows = [item for item in rows if item["uid"] > after]
    if not rows:
        raise GitHubNoSelectedRepositories("No selected repositories to refresh")
    if not receipt_page:
        next_cursor = rows[24]["uid"] if len(rows) > 25 else None
        rows = rows[:25]
    groups = {}
    for item in rows:
        path = {part["type"]: part["id"] for part in item["path"]}
        groups.setdefault((int(path["installation"]), int(path["account"])), []).append(item)
    results = {}
    for (installation_id, account_id), items in groups.items():
        try:
            verified = inspect_installation(
                service,
                actor,
                project_uid,
                connection_uid,
                installation_id,
                account_id,
                repository_ids=tuple(int(item["repository_id"]) for item in items),
            )
            repositories = {str(item["id"]): item for item in verified["repositories"]}
            for item in items:
                repository = repositories[item["repository_id"]]
                results[item["uid"]] = ("granted", "degraded" if repository["archived"] else "healthy")
        except GitHubManifestUnavailable:
            # Ambiguous group failure cannot identify a specific inaccessible repo.
            for item in items:
                results[item["uid"]] = ("unknown", "unavailable")
    with DbSession.atomic() as db:
        board = db.exec(SqlBuilder.select.table(Project).where(Project.id == board.id).with_for_update()).first()
        _board(service, actor, project_uid)
        current = db.exec(
            SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection.id).with_for_update()
        ).first()
        if current is None or connection_revision(current) != revision:
            raise GitHubResourceConflict()
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.id == binding.id).with_for_update()
        ).first()
        current_snapshot = (
            _receipt_page(db, binding, connection.id, installation_scope, repository_scope, after, lock=True)[0]
            if receipt_page
            else resource_snapshot(db, binding)
        )
        if current_snapshot["revision"] != expected_revision:
            raise GitHubResourceConflict()
        for uid, (access, health) in results.items():
            row = db.exec(
                SqlBuilder.select.table(AppResourceBinding)
                .where(AppResourceBinding.id == InfraHelper.convert_id(uid))
                .with_for_update()
            ).first()
            row.access_state, row.health = access, health
            db.update(row)
        if results:
            db.after_commit(lambda: CardPublisher.app_signal_changed(project_uid))
        return {
            **({} if receipt_page else resource_snapshot(db, binding)),
            "next_cursor": next_cursor,
            "refreshed_count": len(results),
            "unavailable_count": sum(access == "unknown" for access, _ in results.values()),
        }
