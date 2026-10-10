"""Bounded resource reads require current board consent, never identity alone."""

from ...core.db import DbSession, SqlBuilder
from ..models import AppConnection, AppDefinition, AppResourceBinding, BoardAppBinding, Project, ProjectRole, User
from .AppConnectionAuthentication import authenticate_connection_credential
from .AppGovernance import AppGovernanceDenied, _current, require_connection_access
from .AppManifest import APP_MANIFESTS


class AppResourceCredentialDenied(AppGovernanceDenied):
    """Distinguish invalid identity from an authenticated board-scope denial."""


def list_connection_resources(token, project_id, *, after_id=None, limit=25):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Resource page limit must be 1 to 50")
    with DbSession.atomic() as db:
        try:
            principal = authenticate_connection_credential(token)
        except AppGovernanceDenied as exc:
            raise AppResourceCredentialDenied() from exc
        connection = _current(db, AppConnection, principal.connection_id, for_update=False)
        project = _current(db, Project, project_id, for_update=False)
        actor = _current(db, User, principal.owner_id, for_update=False)
        if project is None or actor is None or connection is None:
            raise AppGovernanceDenied()
        # App credentials represent autonomous callers, not a user's interactive action.
        require_connection_access(db, actor, project, connection, unattended=True)
        if project.owner_id != actor.id:
            role = db.exec(
                SqlBuilder.select.table(ProjectRole).where(
                    ProjectRole.project_id == project.id,
                    ProjectRole.user_id == actor.id,
                )
            ).first()
            if role is None or not role.is_granted("read"):
                raise AppGovernanceDenied()
        definition = db.exec(
            SqlBuilder.select.table(AppDefinition).where(
                AppDefinition.key == principal.app_key,
            )
        ).first()
        if definition is None:
            manifest = APP_MANIFESTS.get(principal.app_key)
            capabilities = manifest.capabilities if manifest else ()
            resource_types = manifest.resource_types if manifest else ()
        else:
            capabilities = definition.declaration.get("capabilities", [])
            resource_types = definition.declaration.get("resource_types", [])
        binding = db.exec(
            SqlBuilder.select.table(BoardAppBinding).where(
                BoardAppBinding.project_id == project.id,
                BoardAppBinding.app_key == principal.app_key,
            )
        ).first()
        if (
            "resources.read" not in capabilities
            or binding is None
            or binding.state != "enabled"
            or "resources.read" not in binding.granted_capabilities
        ):
            raise AppGovernanceDenied()
        statement = SqlBuilder.select.table(AppResourceBinding).where(
            AppResourceBinding.board_binding_id == binding.id,
            AppResourceBinding.connection_id == connection.id,
            AppResourceBinding.resource_type.in_(resource_types),
            AppResourceBinding.is_selected == True,  # noqa: E712
            AppResourceBinding.access_state == "granted",
        )
        if after_id is not None:
            statement = statement.where(AppResourceBinding.id > after_id)
        rows = db.exec(statement.order_by(AppResourceBinding.id).limit(limit + 1)).all()
        page = rows[:limit]
        return {
            "schema_version": 1,
            "connection_uid": connection.get_uid(),
            "binding_revision": binding.edit_revision(),
            "items": [
                {
                    "resource_uid": row.get_uid(),
                    "resource_type": row.resource_type,
                    "external_resource_id": row.external_resource_id,
                    "resource_path": row.resource_path,
                    "access_revision": row.access_revision,
                    "health": row.health,
                }
                for row in page
            ],
            "next_cursor": page[-1].get_uid() if len(rows) > limit else None,
        }
