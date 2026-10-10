# ruff: noqa: F811
"""An independent adapter uses shared workflow resolution without core name branches."""

import importlib
from langboard_shared.core.db import DbSession
from langboard_shared.domain.services.AppManifest import AppManifest, AppSignalPolicy
from langboard_shared.domain.services.AppWorkflowPolicy import WorkflowRequirements
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401


def test_independent_adapter_builtin_stage_and_many_resources(board, monkeypatch):
    from langboard_shared.domain.models import AppConnection, AppResourceBinding
    from langboard_shared.domain.services.AppSignalProjection import (
        provider_resource_condition,
        supported_signal_condition,
    )
    from sqlalchemy import select

    stage_service, actor, project, _, role, columns, _ = board
    manifests = importlib.import_module("langboard_shared.domain.services.AppManifest")
    service_module = importlib.import_module("langboard_shared.domain.services.factory.WorkflowStageService")
    adapter = AppManifest(
        "example-monitor", "Example Monitor", ("service",), ("signals.read",),
        WorkflowRequirements(("active",)),
        signal_policy=AppSignalPolicy(("incident.observed",), ("service",)),
    )
    registry = {**manifests.APP_MANIFESTS, adapter.key: adapter}
    monkeypatch.setattr(manifests, "APP_MANIFESTS", registry)
    monkeypatch.setattr(service_module, "APP_MANIFESTS", registry)
    # Workflow lookup now uses the current approved registry boundary as well.
    approval_registry = importlib.import_module("langboard_shared.domain.services.AppRegistry")
    monkeypatch.setattr(approval_registry, "APP_MANIFESTS", registry)
    with DbSession.use(readonly=False) as db:
        role.actions = ["read", "update"]
        db.update(role)
    draft = stage_service.prepare_app_mapping(actor, project.get_uid(), adapter.key)
    assert draft.workflow_mapping == {"active": columns[0].get_uid()}
    snapshot = stage_service.get_app_mapping(actor, project.get_uid(), adapter.key)
    assert snapshot["mapping"].transitions_enabled
    # One board binding accepts several independent resource identities.
    with DbSession.use(readonly=False) as db:
        connection = AppConnection(app_key=adapter.key, owner_id=actor.id, state="connected")
        db.insert(connection)
        resources = [AppResourceBinding(
            board_binding_id=draft.id, connection_id=connection.id,
            resource_type="service", external_resource_id=name,
        ) for name in ("first", "second")]
        for resource in resources:
            db.insert(resource)
        assert len(db.exec(select(AppResourceBinding).where(AppResourceBinding.board_binding_id == draft.id)).all()) == 2
    # Shared SQL includes the independently installed declaration.
    for predicate in (supported_signal_condition(), provider_resource_condition()):
        sql = str(predicate.compile(compile_kwargs={"literal_binds": True}))
        assert "example-monitor" in sql
