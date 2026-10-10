# ruff: noqa: F811
"""SDK workflow management exercises authenticated native HTTP and current roles."""

from types import SimpleNamespace
import langboard.routes.board.BoardSettingApi  # noqa: F401
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard_sdk import AppManager, GlitchTipProject, HttpTransport, NativeApiError, WorkflowStage
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import binding, board  # noqa: F401
from langboard_shared.Env import Env
from test_glitchtip_connection import secrets, setup  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize("revocation", ["policy", "registry"])
async def test_disabled_apps_remain_revocable_through_native_http(board, binding, monkeypatch, tmp_path, revocation):
    from langboard_shared.domain.models import AppDefinition, AppGovernancePolicy, BoardAppBinding

    monkeypatch.setattr(type(Env), "CACHE_DIR", property(lambda _: tmp_path / "cache"))
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    with DbSession.use(readonly=False) as db:
        if revocation == "policy":
            db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
        else:
            db.insert(AppDefinition(key="github", declaration={"capabilities": []}, is_enabled=False))
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        manager = AppManager(HttpTransport(SimpleNamespace(request=request)), board[2].get_uid())
        with pytest.raises(NativeApiError) as hidden:
            await manager.workflow("github")
        assert hidden.value.status_code == 404
        with pytest.raises(NativeApiError) as conflict:
            await manager.disable("github", binding.get_uid(), "0" * 64)
        assert conflict.value.status_code == 409
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        with pytest.raises(NativeApiError) as denied:
            await manager.disable("github", binding.get_uid(), binding.edit_revision())
        assert denied.value.status_code == 404
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read", "update"]
            db.update(board[4])
        disabled = await manager.disable("github", binding.get_uid(), binding.edit_revision())
        assert disabled["state"] == "disabled"
        with DbSession.use(readonly=False) as db:
            stored = db.exec(SqlBuilder.select.table(BoardAppBinding).where(BoardAppBinding.id == binding.id)).first()
            assert stored.granted_capabilities == []
            assert not stored.stage_transitions_enabled
        with pytest.raises(NativeApiError):
            await manager.workflow("github")


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_management_roundtrip_conflict_and_role_revocation(board, binding, monkeypatch):
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        manager = AppManager(HttpTransport(SimpleNamespace(request=request)), board[2].get_uid())
        current = await manager.workflow("github")
        revision = current["binding"]["revision"]
        mapping = {
            WorkflowStage(choice["stage"]): choice["column_uid"]
            for choice in current["choices"]
            if choice["column_uid"]
        }
        saved = await manager.save_workflow("github", binding.get_uid(), revision, mapping)
        assert not saved["binding"]["stage_transitions_enabled"]
        assert saved["binding"]["workflow_mapping"] == {stage.value: uid for stage, uid in mapping.items()}
        with pytest.raises(NativeApiError) as stale:
            await manager.save_workflow("github", binding.get_uid(), revision, mapping)
        assert stale.value.status_code == 409
        disabled = await manager.disable("github", binding.get_uid(), saved["binding"]["revision"])
        assert disabled["state"] == "disabled"
        assert (await manager.workflow("github"))["binding"]["revision"] == disabled["revision"]
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        with pytest.raises(NativeApiError) as denied:
            await manager.disable("github", binding.get_uid(), disabled["revision"])
        # The native service masks unavailable board bindings with 404.
        assert denied.value.status_code == 404
        assert (await manager.workflow("github"))["binding"]["revision"] == disabled["revision"]


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_instance_resource_lifecycle_uses_native_http(setup, monkeypatch):
    import langboard.routes.board.BoardGlitchTipAppApi  # noqa: F401

    _, board, reference, _, _ = setup
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        manager = AppManager(HttpTransport(SimpleNamespace(request=request)), board[2].get_uid())
        connections = manager.connections("glitchtip", selection_collection="projects")
        connection = await connections.create("https://errors.example.invalid", reference["uri"])
        uid = connection["connection_uid"]
        assert (await connections.list())["items"][0]["connection_uid"] == uid
        discovered = await connections.discover(uid, organization="test-org")
        assert discovered["items"][0]["slug"] == "test-project"
        selected = await connections.select(uid, connection["revision"], GlitchTipProject("test-org", "test-project"))
        assert (await connections.selected(uid))["items"][0]["resource_uid"] == selected["resource_uid"]
        removed = await connections.remove(uid, selected["resource_uid"], selected["access_revision"])
        assert removed["selected"] is False
        assert (await connections.selected(uid))["items"][0]["selected"] is False
        current = (await connections.list())["items"][0]
        disconnected = await connections.disconnect(uid, current["revision"])
        assert disconnected["state"] == "disconnected"
        assert (await connections.list())["items"] == []
        from langboard_shared.core.db import SqlBuilder
        from langboard_shared.domain.models import AppConnection, SecretReference

        with DbSession.use(readonly=False) as db:
            stored = db.exec(SqlBuilder.select.table(AppConnection)).first()
            secret = db.exec(SqlBuilder.select.table(SecretReference)).first()
            assert stored.state == "disconnected"
            assert secret.state == "active"
