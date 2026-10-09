# ruff: noqa: F811
"""SDK webhook management verifies native revision and provider configuration fences."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.board import BoardDokployAppApi  # noqa: F401
from langboard_sdk import DokployManager, HttpTransport, NativeApiError
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.Env import Env
from test_dokploy_notification_config import board, configured, ready, secrets, setup  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_webhook_verify_reconfigure_and_disable(ready, monkeypatch):
    configured, callback, _, calls = ready
    setup, conn, reference, config = configured
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
        verified = await manager.verify_webhook(
            conn["connection_uid"], conn["revision"], config["binding_revision"], config["config_revision"], callback
        )
        assert verified["provider_config"] == "matched" and len(calls) == 1
        current = await manager.webhook_health(conn["connection_uid"])
        updated = await manager.configure_webhook(
            conn["connection_uid"],
            conn["revision"],
            current["binding_revision"],
            current["config_revision"],
            reference["uri"],
        )
        assert updated["config_revision"] > current["config_revision"]
        with pytest.raises(NativeApiError) as stale:
            await manager.disable_webhook(
                conn["connection_uid"], conn["revision"], current["binding_revision"], current["config_revision"]
            )
        assert stale.value.status_code == 409
        disabled = await manager.disable_webhook(
            conn["connection_uid"], conn["revision"], updated["binding_revision"], updated["config_revision"]
        )
        assert disabled["state"] == "disabled"
        assert (await manager.webhook_health(conn["connection_uid"]))["state"] == "disabled"
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        with pytest.raises(NativeApiError) as denied:
            await manager.webhook_health(conn["connection_uid"])
        assert denied.value.status_code == 404
