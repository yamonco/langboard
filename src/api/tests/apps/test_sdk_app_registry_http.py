# ruff: noqa: F811
"""Independent external app registration using authenticated SDK HTTP, no registry patch."""

from types import SimpleNamespace
import langboard.routes.board.BoardSettingApi  # noqa: F401
import langboard.routes.settings.AppRegistrySettingsApi  # noqa: F401
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard_sdk import AppManager, AppRegistry, HttpTransport, NativeApiError
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env


@pytest.fixture(autouse=True)
def app_notifications(monkeypatch):
    from langboard_shared.publishers import AppSettingPublisher
    events = []
    monkeypatch.setattr(AppSettingPublisher, "apps_changed", lambda: events.append("apps:changed"))
    return events


DECLARATION = {
    "schema_version": 1, "key": "example-erp", "version": "1.0.0", "name": "Example ERP",
    "description": "A separately hosted ERP issue integration.",
    "capabilities": ["cards.create", "cards.presentation"], "resource_types": ["issue"],
    "workflow_requirements": {"required": ["backlog"], "optional": ["active"]},
    "panel": {"url": "https://erp.example.invalid/panel", "name": "ERP outbox", "icon": "📋"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_registration_workflow_update_disable_and_admin_revocation(board, monkeypatch):
    from langboard_shared.domain.models import BoardAppBinding

    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    actor = board[1]
    with DbSession.use(readonly=False) as db:
        actor.is_admin = True
        db.update(actor)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        transport = HttpTransport(SimpleNamespace(request=request))
        registry = AppRegistry(transport)
        manager = AppManager(transport, board[2].get_uid())
        saved = await registry.approve(DECLARATION)
        assert saved["is_enabled"] and saved["generation"] == 1
        assert (await registry.list())[0]["declaration"] == DECLARATION
        entry = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")
        assert entry["panel"] == DECLARATION["panel"]
        assert entry["version"] == "1.0.0"
        assert entry["connection_setup_available"] is False
        assert entry["binding"] is None
        draft = await manager.prepare_workflow("example-erp")
        assert next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")["binding"]["granted_capabilities"] == []
        assert not draft["binding"]["stage_transitions_enabled"]
        assert {c["stage"] for c in draft["choices"]} == {"backlog", "active"}
        with pytest.raises(NativeApiError) as duplicate:
            await registry.approve(DECLARATION)
        assert duplicate.value.status_code == 409
        with pytest.raises(NativeApiError) as builtin:
            await registry.approve({**DECLARATION, "key": "github"})
        assert builtin.value.status_code == 400
        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.app_key == "example-erp")).first()
            binding.state = "enabled"
            binding.granted_capabilities = ["cards.create"]
            binding.stage_transitions_enabled = True
            db.update(binding)
        updated = await registry.approve({**DECLARATION, "version": "1.1.0"}, expected_revision=saved["revision"])
        assert updated["generation"] == 2
        snapshot = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")["binding"]
        assert snapshot["state"] == "disabled" and snapshot["granted_capabilities"] == []
        assert not snapshot["stage_transitions_enabled"]
        with pytest.raises(NativeApiError) as stale:
            await registry.disable("example-erp", saved["revision"])
        assert stale.value.status_code == 409
        disabled = await registry.disable("example-erp", updated["revision"])
        assert not disabled["is_enabled"] and disabled["generation"] == 3
        assert "example-erp" not in {a["key"] for a in (await manager.catalog())["apps"]}
        with DbSession.use(readonly=False) as db:
            actor.is_admin = False
            db.update(actor)
        with pytest.raises(NativeApiError) as revoked:
            await registry.approve({**DECLARATION, "version": "1.2.0"}, expected_revision=disabled["revision"])
        assert revoked.value.status_code == 403


def test_registry_migration_preserves_approved_definitions():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from langboard_shared.domain.models import AppDefinition, User
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261010002000-c62943df05b8.py"
    spec = importlib.util.spec_from_file_location("registry_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert {c["name"] for c in inspect(connection).get_columns("app_definition")} == set(AppDefinition.__table__.columns.keys())
        with Session(connection) as db:
            from langboard_shared.core.types import SafeDateTime
            db.add(AppDefinition(id=100, key="example-erp", declaration=DECLARATION, approved_by=1,
                                 created_at=SafeDateTime.now(), updated_at=SafeDateTime.now()))
            db.flush()
        with pytest.raises(RuntimeError, match="Cannot discard"):
            module.downgrade()
        assert connection.execute(text("SELECT count(*) FROM app_definition")).scalar() == 1
        connection.execute(text("DELETE FROM app_definition"))
        module.downgrade()
        assert "app_definition" not in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_panel_consent_scope_revisions_and_revocation(board, monkeypatch, app_notifications):
    from langboard_shared.domain.models import BoardAppBinding

    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    actor = board[1]
    with DbSession.use(readonly=False) as db:
        actor.is_admin = True
        db.update(actor)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        transport = HttpTransport(SimpleNamespace(request=request))
        registry = AppRegistry(transport)
        manager = AppManager(transport, board[2].get_uid())
        declaration = {**DECLARATION, "capabilities": ["panels.render"], "workflow_requirements": None}
        approved = await registry.approve(declaration)
        with pytest.raises(NativeApiError) as no_consent:
            await manager.panel("example-erp")
        assert no_consent.value.status_code == 404
        saved = (await manager.set_panel_consent("example-erp", approved["revision"], enabled=True))["binding"]
        assert saved["granted_capabilities"] == ["panels.render"]
        snapshot = await manager.panel("example-erp")
        assert snapshot["panel"] == declaration["panel"]
        assert snapshot["app_revision"] == approved["revision"]
        with DbSession.use(readonly=False) as db:
            binding = db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.app_key == "example-erp")).first()
            assert binding.workflow_mapping == {} and not binding.stage_transitions_enabled
            actor.is_admin = False
            db.update(actor)
        # A read-only board member can read the consented panel, but cannot grant it.
        assert (await manager.panel("example-erp"))["key"] == "example-erp"
        with pytest.raises(NativeApiError) as denied:
            await manager.set_panel_consent("example-erp", approved["revision"], enabled=False,
                                            binding_uid=saved["uid"], expected_revision=saved["revision"])
        assert denied.value.status_code in (403, 404)
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read", "update"]
            db.update(board[4])
        notification_count = len(app_notifications)
        with pytest.raises(NativeApiError) as stale:
            await manager.set_panel_consent("example-erp", "0" * 64, enabled=False,
                                            binding_uid=saved["uid"], expected_revision=saved["revision"])
        assert stale.value.status_code == 409
        assert len(app_notifications) == notification_count
        disabled = (await manager.set_panel_consent("example-erp", approved["revision"], enabled=False,
                                                   binding_uid=saved["uid"], expected_revision=saved["revision"]))["binding"]
        assert disabled["granted_capabilities"] == []
        with pytest.raises(NativeApiError):
            await manager.panel("example-erp")
        restored = (await manager.set_panel_consent("example-erp", approved["revision"], enabled=True,
                                                   binding_uid=disabled["uid"], expected_revision=disabled["revision"]))["binding"]
        assert restored["granted_capabilities"] == ["panels.render"]
        with DbSession.use(readonly=False) as db:
            actor.is_admin = True
            db.update(actor)
        newer = await registry.approve({**declaration, "version": "1.1.0"}, expected_revision=approved["revision"])
        with pytest.raises(NativeApiError):
            await manager.panel("example-erp")
        entry = next(a for a in (await manager.catalog())["apps"] if a["key"] == "example-erp")
        assert entry["app_revision"] == newer["revision"]
        restored = (await manager.set_panel_consent("example-erp", newer["revision"], enabled=True,
            binding_uid=entry["binding"]["uid"], expected_revision=entry["binding"]["revision"]))["binding"]
        await registry.disable("example-erp", newer["revision"])
        with pytest.raises(NativeApiError):
            await manager.panel("example-erp")
