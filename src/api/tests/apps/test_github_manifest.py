# ruff: noqa: F811
"""Manifest callback scope/session/replay and real host credential persistence."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from langboard.apps import GitHubManifest as github
from langboard_shared.core.caching import Cache
from langboard_shared.core.caching.InMemoryCache import InMemoryCache
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import AppConnection, SecretReference
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from sqlalchemy import select


@pytest.fixture
def setup(secrets, monkeypatch, tmp_path):
    secret_service, board, vault_path = secrets
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    monkeypatch.setattr(type(Env), "CACHE_DIR", property(lambda _: tmp_path / "cache"))
    monkeypatch.setattr(Cache, "_cache", InMemoryCache())
    service = SimpleNamespace(workflow_stage=board[0], secret_reference=secret_service)
    payload, session = github.begin_manifest(service, board[1], board[2].get_uid())
    state = parse_qs(urlsplit(payload["registration_url"]).query)["state"][0]
    calls = []

    def exchange(request):
        calls.append(request)
        assert request.method == "POST" and request.url.host == "api.github.com"
        assert request.url.path.endswith("/conversions")
        return httpx.Response(
            201,
            json={
                "id": 42,
                "slug": "langboard-fixture",
                "pem": "fixture-private-key",
                "webhook_secret": "fixture-signing",
                "client_id": "fixture-client",
                "client_secret": "fixture-client-secret",
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        github.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(exchange), **kwargs)
    )
    return service, board, payload, session, state, calls


def test_manifest_exchange_is_pending_and_credentials_not_public(setup):
    service, board, payload, session, state, calls = setup
    assert payload["manifest"]["hook_attributes"]["active"] is False
    assert set(payload["manifest"]["default_permissions"].values()) == {"read"}
    result = github.complete_manifest(service, board[1], board[2].get_uid(), state, "a" * 40, session)
    assert result["state"] == "pending" and not result["installation_verified"]
    assert result["installation_url"] == "https://github.com/apps/langboard-fixture/installations/new"
    assert "fixture-private-key" not in json.dumps(result)
    with DbSession.use(readonly=False) as db:
        connection = db.exec(select(AppConnection)).first()[0]
        reference = db.exec(select(SecretReference)).first()[0]
    assert connection.credential_reference == reference.metadata()["uri"]
    assert (
        json.loads(
            service.secret_reference.resolve_for_runtime(board[1], connection.credential_reference).get_secret_value()
        )["pem"]
        == "fixture-private-key"
    )
    with pytest.raises(github.GitHubManifestUnavailable):
        github.complete_manifest(service, board[1], board[2].get_uid(), state, "a" * 40, session)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["session", "board", "expired", "revoked"])
def test_callback_rejects_wrong_context_before_exchange(setup, failure):
    service, board, payload, session, state, calls = setup
    project_uid = board[2].get_uid()
    if failure == "session":
        session = "wrong-session"
    elif failure == "board":
        project_uid = "b"
    elif failure == "expired":
        Cache.delete("github-manifest:" + github._digest(state))
    else:
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
    with pytest.raises(github.GitHubManifestUnavailable):
        github.complete_manifest(service, board[1], project_uid, state, "a" * 40, session)
    assert not calls
    with DbSession.use(readonly=False) as db:
        assert not db.exec(select(AppConnection)).all()


def test_wrong_session_does_not_consume_valid_state(setup):
    service, board, payload, session, state, calls = setup
    with pytest.raises(github.GitHubManifestUnavailable):
        github.complete_manifest(service, board[1], board[2].get_uid(), state, "a" * 40, "wrong")
    assert (
        github.complete_manifest(service, board[1], board[2].get_uid(), state, "a" * 40, session)["state"] == "pending"
    )


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_http_manifest_cookie_and_complete(setup, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import finish_github_manifest, start_github_manifest
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, board, _, _, _, calls = setup
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in (start_github_manifest, finish_github_manifest):
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": f"Bearer {access}"}
    url = f"/board/{board[2].get_uid()}/settings/apps/github/manifest"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        started = client.post(url, headers=headers)
        assert started.status_code == 200
        assert "HttpOnly" in started.headers["set-cookie"] and "SameSite=lax" in started.headers["set-cookie"]
        state = parse_qs(urlsplit(started.json()["registration_url"]).query)["state"][0]
        result = client.post(url + "/complete", headers=headers, json={"state": state, "code": "a" * 40})
        assert result.status_code == 200, result.text
        assert result.json()["state"] == "pending"
        assert not result.json()["installation_verified"]
        assert "fixture-private-key" not in result.text
        assert (
            client.post(url + "/complete", headers=headers, json={"state": state, "code": "a" * 40}).status_code == 400
        )
        assert len(calls) == 1
