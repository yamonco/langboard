"""Revision-checked repository deltas preserve unrelated board resource selections."""

import hashlib
import json
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding, Project, User
from langboard_shared.domain.services import DomainService
from langboard_shared.helpers import InfraHelper
from .GitHubInstallation import connection_revision, inspect_installation
from .GitHubManifest import GitHubManifestUnavailable, _board


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
    items = sorted(
        [
            {
                "uid": row.get_uid(),
                "connection_uid": InfraHelper.convert_uid(row.connection_id),
                "repository_id": row.external_resource_id,
                "selected": row.is_selected,
                "path": row.resource_path,
                "access_state": row.access_state,
                "health": row.health,
            }
            for row in rows
        ],
        key=lambda item: item["uid"],
    )
    revision = hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"items": items, "revision": revision}


def get_resources(service: DomainService, actor: User, project_uid: str) -> dict:
    board = _board(service, actor, project_uid)
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
) -> dict:
    if not add and not remove or len(add) > 25 or len(remove) > 25 or set(add) & set(remove):
        raise ValueError("Invalid repository delta")
    if (
        any(type(uid) is not int or uid <= 0 for uid in add + remove)
        or len(set(add)) != len(add)
        or len(set(remove)) != len(remove)
    ):
        raise ValueError("Invalid repository identifiers")
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
        _board(service, actor, project_uid)
        connection = db.exec(
            SqlBuilder.select.table(AppConnection)
            .where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.app_key == "github",
                AppConnection.owner_id == actor.id,
            )
            .with_for_update()
        ).first()
        if connection is None or connection.state not in {"pending", "connected"}:
            raise GitHubManifestUnavailable()
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
        return resource_snapshot(db, binding)
