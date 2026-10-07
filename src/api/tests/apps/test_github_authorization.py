# ruff: noqa: F811
"""PKCE, current host authority and GitHub user installation visibility."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from langboard.apps import GitHubAuthorization as authorization
from langboard_shared.core.caching import Cache
from langboard_shared.core.caching.InMemoryCache import InMemoryCache
from langboard_shared.core.db import DbSession
from langboard_shared.Env import Env
from pydantic import SecretStr
from test_github_installation import board, installation, secrets  # noqa: F401


@pytest.fixture
def authorized(installation, monkeypatch, tmp_path):
    service, board, connection, calls, responses = installation
    monkeypatch.setattr(type(Env), "CACHE_DIR", property(lambda _: tmp_path / "cache"))
    monkeypatch.setattr(Cache, "_cache", InMemoryCache())
    meta = service.secret_reference.create(
        board[1],
        "personal",
        "me",
        "github/oauth",
        SecretStr(json.dumps({"id": 42, "client_id": "fixture-client", "client_secret": "fixture-secret"})),
    )
    with DbSession.use(readonly=False) as db:
        connection.credential_reference = meta["uri"]
        db.update(connection)
    payload, session = authorization.begin_authorization(service, board[1], board[2].get_uid(), connection.get_uid())
    query = parse_qs(urlsplit(payload["authorization_url"]).query)
    calls.clear()
    controls = {"app_id": 42, "revoke": 204}
    # Installation fixture replaced httpx.Client; use the actual class again.
    from httpx._client import Client

    def api(request):
        calls.append(request)
        if request.url.path == "/login/oauth/access_token":
            body = parse_qs(request.content.decode())
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"][0].encode()).digest())
                .decode()
                .rstrip("=")
            )
            assert challenge == query["code_challenge"][0]
            return httpx.Response(200, json={"access_token": "fixture-user-token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 8, "login": "fixture-user"})
        if request.url.path == "/user/installations":
            if controls.get("host_revoke"):
                with DbSession.use(readonly=False) as db:
                    connection.state = "revoked"
                    db.update(connection)
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "installations": [
                        {
                            "id": 17,
                            "app_id": controls["app_id"],
                            "account": {"id": 7, "login": "fixture-org", "type": "Organization"},
                        }
                    ],
                },
            )
        assert request.method == "DELETE" and request.url.path == "/applications/fixture-client/token"
        assert json.loads(request.content)["access_token"] == "fixture-user-token"
        return httpx.Response(controls["revoke"])

    monkeypatch.setattr(
        authorization.httpx, "Client", lambda **kwargs: Client(transport=httpx.MockTransport(api), **kwargs)
    )
    return service, board, connection, query["state"][0], session, calls, controls


def test_user_installations_require_pkce_and_return_no_token(authorized):
    service, board, connection, state, session, calls, controls = authorized
    result = authorization.complete_authorization(service, board[1], board[2].get_uid(), state, "a" * 40, session)
    assert result["installations"][0]["id"] == 17 and not result["binding_created"]
    assert "fixture-user-token" not in json.dumps(result) and calls[-1].method == "DELETE"
    with pytest.raises(authorization.GitHubManifestUnavailable):
        authorization.complete_authorization(service, board[1], board[2].get_uid(), state, "a" * 40, session)
    assert len(calls) == 4
    authorization.require_installation_proof(
        board[1],
        board[2].get_uid(),
        connection.get_uid(),
        17,
        7,
        result["installation_proof"],
        authorization.connection_revision(connection),
    )


@pytest.mark.parametrize("failure", ["session", "expired", "revoked", "app", "revoke_token", "host_revoke"])
def test_authorization_failure_is_closed(authorized, failure):
    service, board, connection, state, session, calls, controls = authorized
    if failure == "session":
        session = "wrong"
    elif failure == "expired":
        Cache.delete("github-authorization:" + authorization._digest(state))
    elif failure == "revoked":
        with DbSession.use(readonly=False) as db:
            connection.state = "revoked"
            db.update(connection)
    elif failure == "app":
        controls["app_id"] = 43
    elif failure == "host_revoke":
        controls["host_revoke"] = True
    else:
        controls["revoke"] = 403
    with pytest.raises(authorization.GitHubManifestUnavailable):
        authorization.complete_authorization(service, board[1], board[2].get_uid(), state, "a" * 40, session)
    if failure in {"session", "expired", "revoked"}:
        assert not calls
    else:
        assert calls[-1].method == "DELETE"


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_authorization_http_cookie_and_replay(authorized, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import finish_github_authorization, start_github_authorization
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, board, connection, state, session, calls, controls = authorized
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in (start_github_authorization, finish_github_authorization):
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": f"Bearer {access}"}
    url = f"/board/{board[2].get_uid()}/settings/apps/github/authorization"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(url, json={"connection_uid": connection.get_uid()}).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        # Use prepared PKCE state so the mock validates its exact verifier.
        client.cookies.set(authorization.COOKIE, session)
        result = client.post(url + "/complete", headers=headers, json={"state": state, "code": "a" * 40})
        assert result.status_code == 200, result.text
        assert not result.json()["binding_created"] and "fixture-user-token" not in result.text
        assert (
            client.post(url + "/complete", headers=headers, json={"state": state, "code": "a" * 40}).status_code == 400
        )
        started = client.post(url, headers=headers, json={"connection_uid": connection.get_uid()})
        assert started.status_code == 200
        assert "HttpOnly" in started.headers["set-cookie"] and "SameSite=lax" in started.headers["set-cookie"]
