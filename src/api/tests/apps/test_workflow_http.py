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
    get_board_app_catalog,
    disable_board_app,
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
            get_board_app_catalog,
            disable_board_app,
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
        catalog_url = f"/board/{board[2].get_uid()}/settings/apps"
        assert client.get(catalog_url).status_code == 401
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401
        draft_url = url.replace("github", "glitchtip")
        first = client.post(draft_url, headers=headers)
        assert first.status_code == 200
        assert first.json()["binding"]["stage_transitions_enabled"] is False
        assert client.post(draft_url, headers=headers).json()["binding"]["uid"] == first.json()["binding"]["uid"]
        catalog = client.get(catalog_url, headers=headers)
        assert catalog.status_code == 200
        assert [item["key"] for item in catalog.json()["apps"]] == ["github", "glitchtip", "dokploy"]
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
        catalog_binding = client.get(catalog_url, headers=headers).json()["apps"][0]["binding"]
        disable_url = f"{catalog_url}/github/disable"
        disable_payload = {"binding_uid": catalog_binding["uid"], "expected_revision": catalog_binding["revision"]}
        assert client.post(disable_url, headers=headers, json=disable_payload).status_code == 200
        assert client.post(disable_url, headers=headers, json=disable_payload).status_code == 409

        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        assert client.get(url, headers=headers).status_code == 200
        assert client.put(url, headers=headers, json=payload).status_code == 403
        assert client.post(disable_url, headers=headers, json=disable_payload).status_code == 403
        with DbSession.use(readonly=False) as db:
            db.delete(board[3])
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(catalog_url, headers=headers).status_code == 404


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_authenticated_missing_stage_creation_persists_and_resolves(board, binding, monkeypatch):
    from langboard_shared.core.db import SqlBuilder
    from langboard.routes.board.BoardColumnApi import create_project_column, update_project_column_workflow_stage
    from langboard_shared.domain.models import ProjectColumn, Card
    from langboard_shared.domain.services.factory.ProjectColumnService import ProjectColumnService
    from langboard_shared.infrastructure.repositories import Repository

    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(Cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(Cache, "set", lambda *a, **k: None)
    with DbSession.use(readonly=False) as db:
        column = board[5][0]
        column.workflow_stage = None
        db.update(column)
        binding.workflow_mapping = {}
        db.update(binding)
    Card.__table__.create(DbEngine.get_main_engine())
    from langboard_shared.publishers import ProjectColumnPublisher
    from langboard_shared.domain.services.factory.CardService import CardService
    monkeypatch.setattr(ProjectColumnPublisher, "workflow_stage_changed", lambda *args: None)
    monkeypatch.setattr(CardService, "publish_work_states", lambda *args: None)
    repository = Repository()
    column_service = ProjectColumnService(lambda _: None, lambda _: None, repository)
    # External socket/activity/bot dispatch is outside this isolated DB test.
    # Validation, order allocation and persistence use the real service/repository.
    monkeypatch.setattr(ProjectColumnService, "dispatch_created", lambda *args, **kwargs: None)
    service = SimpleNamespace(workflow_stage=board[0], project_column=column_service, close=lambda: None)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in (get_app_workflow_mapping, create_project_column, update_project_column_workflow_stage):
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": f"Bearer {access}"}
    board_url = f"/board/{board[2].get_uid()}"
    with TestClient(app) as client:
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        url = f"{board_url}/settings/apps/github/workflow"
        assert client.get(url, headers=headers).json()["choices"][0]["status"] == "missing"
        assert (
            client.post(f"{board_url}/column", json={"name": "Started", "workflow_stage": "active"}).status_code == 401
        )
        created = client.post(
            f"{board_url}/column", headers=headers, json={"name": "Started", "workflow_stage": "active"}
        )
        assert created.status_code == 201, created.text
        uid = created.json()["column"]["uid"]
        snapshot = client.get(url, headers=headers).json()
        assert snapshot["choices"][0]["status"] == "resolved"
        assert snapshot["choices"][0]["column_uid"] == uid
        assert snapshot["binding"]["stage_transitions_enabled"] is False
        stage_url = f"{board_url}/column/{column.get_uid()}/workflow-stage"
        assigned = client.put(stage_url, headers=headers, json={"workflow_stage": "review", "expected_workflow_stage": None})
        assert assigned.status_code == 200, assigned.text
        stale = client.put(stage_url, headers=headers, json={"workflow_stage": "closed", "expected_workflow_stage": None})
        assert stale.status_code == 409, stale.text
        with DbSession.use(readonly=False) as db:
            actual = db.exec(SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.id == column.id)).first()
            assert actual.workflow_stage == "review"

        with DbSession.use(readonly=False) as db:
            rows = db.exec(SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.name == "Started")).all()
            assert len(rows) == 1 and rows[0].workflow_stage == "active" and rows[0].project_id == board[2].id
            stage = board[6][0]
            stage.is_active = False
            db.update(stage)
        assert (
            client.post(
                f"{board_url}/column", headers=headers, json={"name": "Invalid", "workflow_stage": "active"}
            ).status_code
            == 400
        )
        with DbSession.use(readonly=False) as db:
            assert not db.exec(SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.name == "Invalid")).all()
            board[4].actions = ["read"]
            db.update(board[4])
        assert (
            client.post(
                f"{board_url}/column", headers=headers, json={"name": "Denied", "workflow_stage": "review"}
            ).status_code
            == 403
        )
