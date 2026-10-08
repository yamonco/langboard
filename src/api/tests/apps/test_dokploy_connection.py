# ruff: noqa: F811
"""Real host authority and storage with official metadata endpoint contracts."""

import json
from types import SimpleNamespace
import httpx
import pytest
from langboard.apps import DokployConnection as dk
from langboard.apps import MetadataTransport as transport
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from pydantic import SecretStr


@pytest.fixture
def setup(secrets, monkeypatch):
    from langboard_shared.core.caching import Cache
    from langboard_shared.core.caching.InMemoryCache import InMemoryCache

    monkeypatch.setattr(Cache, "_cache", InMemoryCache())
    secret_service, board, _ = secrets
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    service = SimpleNamespace(workflow_stage=board[0], secret_reference=secret_service)
    reference = secret_service.create(board[1], "personal", "me", "dokploy/api", SecretStr("fixture-api-key"))
    original_env = Env.get_from_env
    monkeypatch.setattr(
        Env,
        "get_from_env",
        lambda key, default=None: "https://deploy.example.invalid"
        if key == "APP_CONNECTION_ALLOWED_BASE_URLS"
        else original_env(key, default),
    )
    calls = []
    state = {"failure": None, "after": None}

    def external(request):
        calls.append(request)
        assert request.url.host == "deploy.example.invalid"
        assert request.headers["x-api-key"] == "fixture-api-key"
        assert "Authorization" not in request.headers and request.method == "GET"
        if state["after"]:
            state["after"]()
        if state["failure"] == "redirect":
            return httpx.Response(302, headers={"Location": "https://attacker.invalid"})
        if state["failure"] == "oversize":
            return httpx.Response(200, content=b" " * 262145)
        if state["failure"] == "json":
            return httpx.Response(200, content=b"no json")
        if request.url.path == "/api/project.all":
            return httpx.Response(200, json=[{"projectId": "project-1", "name": "Project", "env": "private"}])
        if request.url.path == "/api/environment.byProjectId":
            assert request.url.params["projectId"] == "project-1"
            return httpx.Response(200, json=[{"environmentId": "env-1", "name": "Production", "env": "private"}])
        assert request.url.path == "/api/environment.one" and request.url.params["environmentId"] == "env-1"
        return httpx.Response(
            200,
            json={
                "environmentId": "env-1",
                "projectId": "project-1",
                "name": "Production",
                "env": "private",
                "applications": [{"applicationId": "app-1", "name": "API", "env": "private"}],
                "compose": [{"composeId": "compose-1", "name": "Stack", "composeFile": "private"}],
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        transport.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(external), **kwargs)
    )
    return service, board, reference, calls, state


def connect(setup):
    service, board, reference, *_ = setup
    return dk.register_connection(
        service, board[1], board[2].get_uid(), "https://deploy.example.invalid/", reference["uri"]
    )


def test_register_and_hierarchy_return_only_safe_metadata(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    assert "fixture-api-key" not in json.dumps(connection) and "credential_reference" not in connection
    args = service, board[1], board[2].get_uid(), connection["connection_uid"]
    assert dk.list_connections(*args[:3])["items"] == [connection]
    assert dk.discover_resources(*args)["items"] == [{"id": "project-1", "type": "project", "name": "Project"}]
    assert dk.discover_resources(*args, "project-1")["items"] == [
        {"id": "env-1", "type": "environment", "name": "Production"}
    ]
    result = dk.discover_resources(*args, "project-1", "env-1")
    assert result["items"] == [
        {"id": "app-1", "type": "application", "name": "API"},
        {"id": "compose-1", "type": "compose", "name": "Stack"},
    ]
    assert "private" not in json.dumps(result) and result["next_cursor"] is None
    assert len(calls) == 5
    with DbSession.use(readonly=False) as db:
        assert not db.exec(SqlBuilder.select.table(AppResourceBinding)).all()
        assert not db.exec(SqlBuilder.select.table(BoardAppBinding)).all()


@pytest.mark.parametrize(
    "bad",
    [
        "http://deploy.example.invalid",
        "https://other.invalid",
        "https://user@deploy.example.invalid",
        "https://deploy.example.invalid?key=private",
    ],
)
def test_unapproved_instance_no_io(setup, bad):
    service, board, reference, calls, _ = setup
    with pytest.raises(ValueError):
        dk.register_connection(service, board[1], board[2].get_uid(), bad, reference["uri"])
    assert not calls


@pytest.mark.parametrize("failure", ["role", "rotation", "endpoint", "disconnect", "redirect", "oversize", "json"])
def test_discovery_rechecks_authority_after_io(setup, failure):
    service, board, reference, calls, state = setup
    connection = connect(setup)

    def change():
        if failure == "rotation":
            service.secret_reference.rotate(board[1], reference["uri"], SecretStr("new-key"), reference["revision"])
        else:
            with DbSession.use(readonly=False) as db:
                if failure == "role":
                    board[4].actions = ["read"]
                    db.update(board[4])
                else:
                    row = db.exec(SqlBuilder.select.table(AppConnection)).first()
                    if failure == "endpoint":
                        row.instance_url = "https://other.invalid"
                    else:
                        row.state = "disconnected"
                    db.update(row)

    if failure in {"role", "rotation", "endpoint", "disconnect"}:
        state["after"] = change
    else:
        state["failure"] = failure
    with pytest.raises((dk.DokployUnavailable, dk.DokployConflict)):
        dk.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
    assert len(calls) == 2


def test_cross_project_environment_rejected(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    with pytest.raises(dk.DokployUnavailable):
        dk.discover_resources(
            service, board[1], board[2].get_uid(), connection["connection_uid"], "project-1", "foreign-env"
        )
    assert len(calls) == 2


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_http_requires_current_board_authority(setup, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board import BoardDokployAppApi as api
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, board, reference, calls, _ = setup
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    endpoints = {api.create_dokploy_connection, api.get_dokploy_connections, api.get_dokploy_resources}
    for route in app.routes:
        if getattr(route, "endpoint", None) in endpoints:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": "Bearer " + access}
    url = f"/board/{board[2].get_uid()}/settings/apps/dokploy/connections"
    form = {"instance_url": "https://deploy.example.invalid", "credential_reference": reference["uri"]}
    with TestClient(app) as client:
        assert client.post(url, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.post(url, headers=headers, json={**form, "api_key": "must-not-be-accepted"}).status_code == 400
        response = client.post(url, headers=headers, json=form)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert "fixture-api-key" not in response.text
        resource_url = url + "/" + response.json()["connection_uid"] + "/resources"
        result = client.get(
            resource_url, headers=headers, params={"external_project_id": "project-1", "environment_id": "env-1"}
        )
        assert result.status_code == 200 and len(result.json()["items"]) == 2 and "private" not in result.text
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
        count = len(calls)
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(resource_url, headers=headers).status_code == 404
        assert client.post(url, headers=headers, json=form).status_code == 404
        assert len(calls) == count


def test_foreign_connection_owner_and_app_rejected_without_io(setup):
    service, board, _, calls, _ = setup
    connection = connect(setup)
    for field, value in (("owner_id", 2), ("app_key", "glitchtip")):
        with DbSession.use(readonly=False) as db:
            row = db.exec(SqlBuilder.select.table(AppConnection)).first()
            row.owner_id, row.app_key = board[1].id, "dokploy"
            setattr(row, field, value)
            db.update(row)
        count = len(calls)
        with pytest.raises(dk.DokployUnavailable):
            dk.discover_resources(service, board[1], board[2].get_uid(), connection["connection_uid"])
        assert len(calls) == count
