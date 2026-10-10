"""Explicit board consent for isolated app panels, independent of automation grants."""

from ...core.db import DbSession, SqlBuilder
from ...helpers import InfraHelper
from ...publishers import AppSettingPublisher
from ..models import AppDefinition, BoardAppBinding, Project
from ..models.ProjectRole import ProjectRoleAction
from .AppGovernance import AppGovernanceDenied, require_app_allowed
from .AppRegistry import AppRegistryConflict


def set_panel(service, actor, project_uid, app_key, binding_uid, expected_revision, app_revision, enabled, read_signals=False):
    with DbSession.atomic() as db:
        board = db.exec(SqlBuilder.select.table(Project).where(Project.id == InfraHelper.convert_id(project_uid)).with_for_update()).first()
        if board is None:
            return None
        project = service._authorized_app_board(actor, board.id, ProjectRoleAction.Update, lock=True)
        if project is None:
            return None
        try:
            require_app_allowed(db, project)
        except AppGovernanceDenied:
            return None
        definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == app_key).with_for_update()).first()
        if definition is None or not definition.is_enabled:
            return None
        if definition.edit_revision() != app_revision:
            raise AppRegistryConflict()
        if not definition.declaration.get("panel") or "panels.render" not in definition.declaration["capabilities"]:
            raise ValueError("This app has no approved panel capability")
        binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(
            BoardAppBinding.project_id == project.id, BoardAppBinding.app_key == app_key,
        ).with_for_update()).first()
        if binding is None:
            if binding_uid is not None or expected_revision is not None or not enabled:
                raise AppRegistryConflict()
            binding = BoardAppBinding(project_id=project.id, app_key=app_key)
            db.insert(binding)
        else:
            if binding.get_uid() != binding_uid:
                return None
            if binding.edit_revision() != expected_revision:
                raise AppRegistryConflict()
        if read_signals and (not enabled or "signals.read" not in definition.declaration["capabilities"]):
            raise ValueError("Signal reads require separate declared consent")
        grants = set(binding.granted_capabilities)
        if enabled:
            grants.add("panels.render")
        else:
            grants.discard("panels.render")
        if enabled and read_signals:
            grants.add("signals.read")
        else:
            grants.discard("signals.read")
        binding.granted_capabilities = sorted(grants)
        binding.state = "enabled" if grants else "disabled"
        # Rendering does not authorize workflow transitions or card mutation.
        db.update(binding)
        db.after_commit(AppSettingPublisher.apps_changed)
        return {"uid": binding.get_uid(), "state": binding.state, "revision": binding.edit_revision(),
                "granted_capabilities": binding.granted_capabilities}


def get_panel(service, actor, project_uid, app_key, *, lock=False):
    with DbSession.atomic() as db:
        if lock:
            board = db.exec(SqlBuilder.select.table(Project).where(Project.id == InfraHelper.convert_id(project_uid)).with_for_update()).first()
            if board is None:
                return None
        project = service._authorized_app_board(actor, project_uid, ProjectRoleAction.Read, lock=lock)
        if project is None:
            return None
        try:
            require_app_allowed(db, project)
        except AppGovernanceDenied:
            return None
        definition_query = SqlBuilder.select.table(AppDefinition).where(
            AppDefinition.key == app_key, AppDefinition.is_enabled == True,  # noqa: E712
        )
        definition = db.exec(definition_query.with_for_update() if lock else definition_query).first()
        binding_query = SqlBuilder.select.table(BoardAppBinding).where(
            BoardAppBinding.project_id == project.id, BoardAppBinding.app_key == app_key,
            BoardAppBinding.state == "enabled",
        )
        binding = db.exec(binding_query.with_for_update() if lock else binding_query).first()
        if definition is None or binding is None or "panels.render" not in binding.granted_capabilities:
            return None
        panel = definition.declaration.get("panel")
        if not panel:
            return None
        return {"key": app_key, "version": definition.declaration["version"], "panel": panel,
                "app_revision": definition.edit_revision(), "binding_revision": binding.edit_revision(),
                "granted_capabilities": list(binding.granted_capabilities)}
