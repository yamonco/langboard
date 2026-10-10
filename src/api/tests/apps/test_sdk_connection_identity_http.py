# ruff: noqa: F811
"""Reviewed wheel consumes authenticated native identity without host source imports."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard_sdk import AppIdentity, ConnectionCredentials, HttpTransport, NativeApiError
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from test_app_connection_credentials import setup


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_sdk_owner_issue_app_identity_and_revocation(board, monkeypatch):
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    actor = board[1]
    connection, _ = setup(actor)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    with TestClient(app) as owner, TestClient(app) as external:
        owner.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)

        async def owner_request(method, path, **kwargs):
            return owner.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        credentials = ConnectionCredentials(HttpTransport(SimpleNamespace(request=owner_request)))
        issued = await credentials.issue(connection.get_uid())

        async def app_request(method, path, **kwargs):
            return external.request(method, path, headers={"Authorization": f"Bearer {issued['token']}"}, **kwargs)

        transport = HttpTransport(SimpleNamespace(request=app_request))
        identity = await AppIdentity(transport).current()
        assert identity["app_key"] == "example-app"
        assert identity["credential_uid"] == issued["credential_uid"]
        with pytest.raises(NativeApiError):
            await ConnectionCredentials(transport).issue(connection.get_uid())
        await credentials.revoke(connection.get_uid(), issued["credential_uid"])
        with pytest.raises(NativeApiError) as denied:
            await AppIdentity(transport).current()
        assert denied.value.status_code == 401
