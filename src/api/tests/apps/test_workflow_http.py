"""Real session JWT, role middleware, request validation and DB workflow command."""

# ruff: noqa: F811
import importlib
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board.BoardSettingApi import (
    get_app_workflow_mapping,
    prepare_app_workflow_mapping,
    update_app_workflow_mapping,
)
from langboard_shared.core.caching import Cache
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import binding, board  # noqa: F401
from langboard_shared.Env import Env


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_authenticated_http_workflow_and_current_revocation(board, binding, monkeypatch):
    # Auth model lookup uses the readonly connection; the host commands still
    # explicitly select the primary. All fixture data is in this isolated engine.
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(Cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(Cache, "set", lambda *a, **k: None)
    service = SimpleNamespace(workflow_stage=board[0], close=lambda: None)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in (
            get_app_workflow_mapping,
            update_app_workflow_mapping,
            prepare_app_workflow_mapping,
        ):
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    url = f"/board/{board[2].get_uid()}/settings/apps/github/workflow"
    headers = {"Authorization": f"Bearer {access}"}
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401
        draft_url = url.replace("github", "glitchtip")
        first = client.post(draft_url, headers=headers)
        assert first.status_code == 200
        assert first.json()["binding"]["stage_transitions_enabled"] is False
        assert client.post(draft_url, headers=headers).json()["binding"]["uid"] == first.json()["binding"]["uid"]
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        payload = {
            "binding_uid": binding.get_uid(),
            "workflow_mapping": None,
            "expected_revision": response.json()["binding"]["revision"],
            "enable_transitions": True,
        }
        injected = client.put(url, headers=headers, json={**payload, "requirements": {"required": ["active"]}})
        assert injected.status_code == 400
        saved = client.put(url, headers=headers, json=payload)
        assert saved.status_code == 200 and saved.json()["binding"]["stage_transitions_enabled"]
        assert client.put(url, headers=headers, json=payload).status_code == 409
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        assert client.get(url, headers=headers).status_code == 200
        assert client.put(url, headers=headers, json=payload).status_code == 403
        with DbSession.use(readonly=False) as db:
            db.delete(board[3])
        assert client.get(url, headers=headers).status_code == 404
