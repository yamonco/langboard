# ruff: noqa: F811
"""SDK deployment refresh runs through authenticated native routes and DB fences."""

from types import SimpleNamespace
import langboard.routes.board.BoardDokployAppApi  # noqa: F401
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard_sdk import DokployManager, HttpTransport, NativeApiError
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.models import AppSignal
from langboard_shared.Env import Env
from test_dokploy_signal import board, secrets, selected, setup  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_deployment_refresh_and_current_consent(selected, monkeypatch):
    setup, conn, chosen, events = selected
    _, board, *_ = setup
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app) as session:
        session.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def request(method, path, **kwargs):
            return session.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        manager = DokployManager(HttpTransport(SimpleNamespace(request=request)), board[2].get_uid())
        current = await manager.selected(conn["connection_uid"])
        enabled = await manager.enable_read(conn["connection_uid"], conn["revision"], current["binding"]["revision"])
        assert enabled["granted_capabilities"] == ["resources.read", "signals.read", "deployments.read"]
        arguments = (conn["connection_uid"], chosen["resource_uid"], conn["revision"], chosen["access_revision"])
        first = await manager.refresh_deployments(*arguments)
        assert first["inserted"] == 1
        assert (await manager.refresh_deployments(*arguments))["inserted"] == 0
        assert len(events) == 1
        assert "private" not in str(first)
        revoked = await manager.disable_read(conn["connection_uid"], conn["revision"], enabled["revision"])
        assert revoked["granted_capabilities"] == [] and revoked["state"] == "disabled"
        count = len(events)
        with pytest.raises(NativeApiError) as consent_denied:
            await manager.refresh_deployments(*arguments)
        assert consent_denied.value.status_code == 404 and len(events) == count
        await manager.enable_read(conn["connection_uid"], conn["revision"], revoked["revision"])
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        with pytest.raises(NativeApiError) as denied:
            await manager.refresh_deployments(*arguments)
        assert denied.value.status_code == 404
        with DbSession.use(readonly=False) as db:
            assert len(db.exec(SqlBuilder.select.table(AppSignal)).all()) == 1
