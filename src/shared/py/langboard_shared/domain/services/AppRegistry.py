"""Persistent external app approval. Current primary admin authority on every edit."""

from dataclasses import replace
from langboard_sdk.definition import validate_app_definition
from langboard_sdk.governance import update_consent
from langboard_sdk.workflow import WorkflowRequirements
from ...core.db import DbSession, SqlBuilder
from ...publishers import AppSettingPublisher
from ..models import AppConnection, AppDefinition, BoardAppBinding, User
from .AppManifest import APP_MANIFESTS, AppManifest


class AppRegistryConflict(Exception):
    pass


class AppRegistryDenied(Exception):
    pass


def _admin(db, actor):
    current = db.exec(SqlBuilder.select.table(User).where(User.id == actor.id).with_for_update()).first()
    if current is None or not current.is_admin or current.deleted_at or not current.activated_at:
        raise AppRegistryDenied()


def list_definitions(actor):
    with DbSession.atomic() as db:
        _admin(db, actor)
        return [row.registry_response() for row in db.exec(SqlBuilder.select.table(AppDefinition).order_by(AppDefinition.key)).all()]


def save_definition(actor, declaration, expected_revision=None):
    declaration = validate_app_definition(declaration)
    key = declaration["key"]
    if key in APP_MANIFESTS:
        raise ValueError("Built-in app declarations are host-owned")
    with DbSession.atomic() as db:
        _admin(db, actor)
        row = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == key).with_for_update()).first()
        if row is None:
            if expected_revision is not None:
                raise AppRegistryConflict()
            row = AppDefinition(key=key, declaration=declaration, approved_by=actor.id)
            db.insert(row)
        else:
            if expected_revision is None or row.edit_revision() != expected_revision:
                raise AppRegistryConflict()
            if tuple(map(int, declaration["version"].split("."))) <= tuple(map(int, row.declaration["version"].split("."))):
                raise ValueError("An app update needs a newer version")
            _update_bindings(db, key, row.declaration, declaration)
            row.declaration = declaration
            row.is_enabled = True
            row.generation += 1
            row.approved_by = actor.id
            db.update(row)
        db.after_commit(AppSettingPublisher.apps_changed)
        return row.registry_response()


def disable_definition(actor, key, expected_revision):
    with DbSession.atomic() as db:
        _admin(db, actor)
        row = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == key).with_for_update()).first()
        if row is None:
            return None
        if row.edit_revision() != expected_revision:
            raise AppRegistryConflict()
        _disable_bindings(db, key)
        row.is_enabled = False
        row.generation += 1
        row.approved_by = actor.id
        db.update(row)
        db.after_commit(AppSettingPublisher.apps_changed)
        return row.registry_response()


def _update_bindings(db, key, previous, current):
    """Keep existing consent only across updates to the same trust targets."""
    trust_changed = update_consent(previous, current, [])["trust_changed"]
    if trust_changed:
        for connection in db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.app_key == key).with_for_update()).all():
            connection.state = "revoked"
            db.update(connection)
    for binding in db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.app_key == key).with_for_update()).all():
        decision = update_consent(previous, current, binding.granted_capabilities)
        binding.granted_capabilities = sorted(decision["retained"])
        if decision["trust_changed"] or not binding.granted_capabilities:
            binding.state = "needs_attention" if decision["trust_changed"] else "disabled"
            binding.stage_transitions_enabled = False
        if "workflow.transition" not in binding.granted_capabilities:
            binding.stage_transitions_enabled = False
        db.update(binding)


def _disable_bindings(db, key):
    for binding in db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.app_key == key).with_for_update()).all():
        binding.state = "disabled"
        binding.granted_capabilities = []
        binding.stage_transitions_enabled = False
        db.update(binding)


def signal_app_allowed(db, key, *, lock=False):
    """Explicit registry overrides fence native adapters; absence retains built-in compatibility."""
    query = SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == key)
    row = db.exec(query.with_for_update() if lock else query).first()
    if row is not None:
        return row.is_enabled and "signals.read" in row.declaration.get("capabilities", [])
    manifest = APP_MANIFESTS.get(key)
    return manifest is not None and "signals.read" in manifest.capabilities


def approved_manifests():
    """No signal adapter or connection route is inferred from an app declaration."""
    result = dict(APP_MANIFESTS)
    with DbSession.use(readonly=False) as db:
        rows = db.exec(SqlBuilder.select.table(AppDefinition)).all()
        for row in rows:
            if not row.is_enabled:
                result.pop(row.key, None)
                continue
            if row.key in APP_MANIFESTS:
                manifest = APP_MANIFESTS[row.key]
                result[row.key] = replace(manifest, capabilities=tuple(
                    capability for capability in manifest.capabilities
                    if capability in row.declaration.get("capabilities", [])
                ))
                continue
            item = validate_app_definition(row.declaration)
            workflow = item.get("workflow_requirements")
            requirements = WorkflowRequirements(tuple(workflow["required"]), tuple(workflow["optional"])) if workflow else None
            result[row.key] = AppManifest(row.key, item["name"], tuple(item["resource_types"]), tuple(item["capabilities"]), requirements,
                version=item["version"], description=item["description"], panel=item.get("panel"))
    return result
