# ruff: noqa: F811
"""Actual RSA app authentication, mocked GitHub authority, current host revocation."""

import json
from types import SimpleNamespace
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from langboard.apps import GitHubInstallation as github
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import AppConnection
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr


@pytest.fixture
def installation(secrets, monkeypatch):
    secret_service, board, path = secrets
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    meta = secret_service.create(
        board[1], "personal", "me", "github/app-42", SecretStr(json.dumps({"id": 42, "pem": pem}))
    )
    with DbSession.use(readonly=False) as db:
        connection = AppConnection(
            app_key="github", owner_id=board[1].id, external_account_id="42", credential_reference=meta["uri"]
        )
        db.insert(connection)
    responses = {
        "account_id": 7,
        "app_id": 42,
        "suspended": None,
        "status": 200,
        "revoke_status": 204,
        "revoke_host": False,
    }
    calls = []

    def api(request):
        calls.append(request)
        assert request.url.host == "api.github.com"
        token = request.headers["authorization"].removeprefix("Bearer ")
        if request.url.path == "/app" or request.url.path.startswith("/app/installations/"):
            claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], issuer="42")
            assert claims["exp"] - claims["iat"] <= 600
        else:
            assert token == "fixture-ephemeral-token"
        if request.url.path == "/app":
            if responses["revoke_host"]:
                with DbSession.use(readonly=False) as db:
                    connection.state = "revoked"
                    db.update(connection)
            return httpx.Response(
                responses["status"],
                json={
                    "id": responses["app_id"],
                    "slug": responses.get("slug", "langboard-fixture"),
                    "html_url": "https://untrusted.invalid",
                    "pem": "must-not-return",
                },
            )
        if request.url.path.endswith("access_tokens"):
            body = json.loads(request.content)
            assert body["permissions"] == {"metadata": "read"}
            responses["repository_ids"] = body.get("repository_ids")
            return httpx.Response(201, json={"token": "fixture-ephemeral-token"})
        if request.url.path == "/installation/repositories":
            if responses["revoke_host"]:
                with DbSession.use(readonly=False) as db:
                    connection.state = "revoked"
                    db.update(connection)
            return httpx.Response(
                200,
                json={
                    "total_count": len(responses["repository_ids"]) if responses.get("repository_ids") else 101,
                    "repositories": [
                        {"id": uid, "full_name": f"fixture/repo-{uid}", "owner": {"id": 7}, "private": True}
                        for uid in responses.get("returned_ids", responses.get("repository_ids") or [99])
                    ],
                },
            )
        if request.url.path == "/installation/token":
            return httpx.Response(responses["revoke_status"])
        return httpx.Response(
            responses["status"],
            json={
                "id": 17,
                "app_id": responses["app_id"],
                "suspended_at": responses["suspended"],
                "account": {"id": responses["account_id"], "login": "fixture", "type": "Organization"},
            },
        )

    original = httpx.Client
    monkeypatch.setattr(github.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(api), **kwargs))
    service = SimpleNamespace(workflow_stage=board[0], secret_reference=secret_service)
    return service, board, connection, calls, responses


def test_repository_inspection_checks_rsa_identity_and_pages_without_token_leak(installation):
    service, board, connection, calls, responses = installation
    result = github.inspect_installation(service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7)
    assert result["next_page"] == 2 and not result["binding_created"]
    assert result["repositories"] == [{"id": 99, "name": "fixture/repo-99", "private": True, "archived": False}]
    assert "fixture-ephemeral-token" not in json.dumps(result)
    assert [call.method for call in calls] == ["GET", "POST", "GET", "DELETE"]


@pytest.mark.parametrize(
    "failure", ["app", "account", "suspended", "external_denied", "token_revoke", "host_revoke", "host_permission"]
)
def test_installation_and_current_authority_failure_is_closed(installation, failure):
    service, board, connection, calls, responses = installation
    if failure == "app":
        responses["app_id"] = 43
    elif failure == "account":
        responses["account_id"] = 8
    elif failure == "suspended":
        responses["suspended"] = "2026-10-08"
    elif failure == "external_denied":
        responses["status"] = 403
    elif failure == "token_revoke":
        responses["revoke_status"] = 403
    elif failure == "host_revoke":
        responses["revoke_host"] = True
    else:
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
    with pytest.raises(github.GitHubManifestUnavailable):
        github.inspect_installation(service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7)
    if failure == "host_permission":
        assert not calls


def test_multi_repository_delta_preserves_foreign_binding_and_other_selection(installation):
    from langboard.apps.GitHubResources import GitHubResourceConflict, get_resources, update_resources
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding
    from sqlalchemy import select

    service, board, connection, calls, responses = installation
    from langboard.apps.GitHubAuthorization import _issue_installation_proof

    proof = _issue_installation_proof(
        board[1], board[2].get_uid(), connection, [{"id": 17, "account": {"id": 7}, "suspended": False}]
    )
    snapshot = get_resources(service, board[1], board[2].get_uid())
    added = update_resources(
        service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99, 100), (), snapshot["revision"], proof
    )
    assert len(added["items"]) == 2 and all(item["selected"] for item in added["items"])
    with DbSession.use(readonly=False) as db:
        foreign = BoardAppBinding(project_id=11, app_key="github", state="enabled")
        db.insert(foreign)
        other = AppResourceBinding(
            board_binding_id=foreign.id,
            connection_id=connection.id,
            resource_type="repository",
            external_resource_id="99",
        )
        db.insert(other)
    removed = update_resources(
        service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (), (99,), added["revision"]
    )
    assert {item["repository_id"]: item["selected"] for item in removed["items"]} == {"99": False, "100": True}
    with pytest.raises(GitHubResourceConflict):
        update_resources(
            service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (), (100,), added["revision"]
        )
    with DbSession.use(readonly=False) as db:
        persisted = db.exec(select(AppResourceBinding).where(AppResourceBinding.id == other.id)).first()[0]
        own = db.exec(select(BoardAppBinding).where(BoardAppBinding.project_id == board[2].id)).first()[0]
        assert persisted.is_selected and own.state == "disabled" and not own.granted_capabilities
    restored = update_resources(
        service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99,), (), removed["revision"], proof
    )
    assert len(restored["items"]) == 2 and all(item["selected"] for item in restored["items"])


@pytest.mark.parametrize("returned_ids", [[99], [99, 101], [99, 100, 100]])
def test_resource_delta_rejects_incomplete_wrong_or_duplicate_external_set(installation, returned_ids):
    from langboard.apps.GitHubResources import get_resources, update_resources

    service, board, connection, calls, responses = installation
    from langboard.apps.GitHubAuthorization import _issue_installation_proof

    proof = _issue_installation_proof(
        board[1], board[2].get_uid(), connection, [{"id": 17, "account": {"id": 7}, "suspended": False}]
    )
    snapshot = get_resources(service, board[1], board[2].get_uid())
    responses["returned_ids"] = returned_ids
    with pytest.raises(github.GitHubManifestUnavailable):
        update_resources(
            service,
            board[1],
            board[2].get_uid(),
            connection.get_uid(),
            17,
            7,
            (99, 100),
            (),
            snapshot["revision"],
            proof,
        )
    assert get_resources(service, board[1], board[2].get_uid()) == snapshot
    assert calls[-1].method == "DELETE"


@pytest.mark.parametrize(
    "failure",
    ["missing", "expired", "actor", "board", "connection", "installation", "account", "revision", "suspended"],
)
def test_repository_add_requires_scoped_user_installation_proof(installation, failure):
    from types import SimpleNamespace
    from langboard.apps.GitHubAuthorization import _digest, _issue_installation_proof
    from langboard.apps.GitHubResources import get_resources, update_resources
    from langboard_shared.core.caching import Cache

    service, board, connection, calls, responses = installation
    actor = SimpleNamespace(id=board[1].id + 1) if failure == "actor" else board[1]
    proof = _issue_installation_proof(
        actor,
        "other" if failure == "board" else board[2].get_uid(),
        connection,
        [
            {
                "id": 18 if failure == "installation" else 17,
                "account": {"id": 8 if failure == "account" else 7},
                "suspended": failure == "suspended",
            }
        ],
    )
    if failure == "missing":
        proof = None
    elif failure == "expired":
        Cache.delete("github-installation-proof:" + _digest(proof))
    elif failure == "connection":
        context = Cache.get("github-installation-proof:" + _digest(proof))
        context["connection"] = "other"
        Cache.set("github-installation-proof:" + _digest(proof), context, 300)
    elif failure == "revision":
        with DbSession.use(readonly=False) as db:
            connection.external_account_id = "43"
            db.update(connection)
    snapshot = get_resources(service, board[1], board[2].get_uid())
    with pytest.raises(github.GitHubManifestUnavailable):
        update_resources(
            service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99,), (), snapshot["revision"], proof
        )
    assert get_resources(service, board[1], board[2].get_uid()) == snapshot
    if failure != "revision":
        assert not calls


def test_connection_discovery_is_owner_scoped_bounded_and_secret_free(installation):
    from langboard.apps.GitHubConnections import list_connections

    service, board, connection, calls, responses = installation
    with DbSession.use(readonly=False) as db:
        foreign = AppConnection(
            app_key="github",
            owner_id=board[2].owner_id,
            external_account_id="foreign",
            credential_reference="secret://hidden",
        )
        db.insert(foreign)
        revoked = AppConnection(app_key="github", owner_id=board[1].id, state="revoked", external_account_id="revoked")
        db.insert(revoked)
        for i in range(51):
            db.insert(AppConnection(app_key="github", owner_id=board[1].id, external_account_id=str(100 + i)))
    first = list_connections(service, board[1], board[2].get_uid())
    second = list_connections(service, board[1], board[2].get_uid(), first["next_cursor"])
    assert len(first["items"]) == 50 and len(second["items"]) == 2 and second["next_cursor"] is None
    assert not set(item["connection_uid"] for item in first["items"]) & set(
        item["connection_uid"] for item in second["items"]
    )
    assert {item["app_id"] for item in first["items"] + second["items"]}.isdisjoint({"foreign", "revoked"})
    assert "credential" not in json.dumps(first) and "secret://" not in json.dumps(first) and not calls
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read"]
        db.update(board[4])
    with pytest.raises(github.GitHubManifestUnavailable):
        list_connections(service, board[1], board[2].get_uid())


@pytest.mark.parametrize("failure", [None, "app", "slug", "host_revoke", "denied", "permission"])
def test_app_metadata_rechecks_identity_and_builds_fixed_install_url(installation, failure):
    from langboard.apps.GitHubConnections import inspect_app

    service, board, connection, calls, responses = installation
    if failure == "app":
        responses["app_id"] = 43
    elif failure == "slug":
        responses["slug"] = "../../bad"
    elif failure == "host_revoke":
        responses["revoke_host"] = True
    elif failure == "denied":
        responses["status"] = 403
    elif failure == "permission":
        with DbSession.use(readonly=False) as db:
            board[4].actions = ["read"]
            db.update(board[4])
    if failure:
        with pytest.raises(github.GitHubManifestUnavailable):
            inspect_app(service, board[1], board[2].get_uid(), connection.get_uid())
        if failure == "permission":
            assert not calls
    else:
        result = inspect_app(service, board[1], board[2].get_uid(), connection.get_uid())
        assert result["installation_url"] == "https://github.com/apps/langboard-fixture/installations/new"
        assert "must-not-return" not in json.dumps(result) and "untrusted.invalid" not in json.dumps(result)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_http_app_metadata_is_authenticated_and_sanitized(installation, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.board.BoardGitHubAppApi import get_github_app
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    service, board, connection, calls, responses = installation
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) == get_github_app:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    with TestClient(app, base_url="https://testserver") as client:
        url = f"/board/{board[2].get_uid()}/settings/apps/github/connections/{connection.get_uid()}/app"
        assert client.get(url).status_code == 401 and not calls
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        result = client.get(url, headers={"Authorization": f"Bearer {access}"})
        assert result.status_code == 200, result.text
        assert result.json()["installation_url"] == "https://github.com/apps/langboard-fixture/installations/new"
        assert "must-not-return" not in result.text and "secret://" not in result.text


@pytest.mark.parametrize("failure", [None, "external", "host_revoke", "stale"])
def test_explicit_health_refresh_preserves_selection_and_foreign_board(installation, failure):
    from langboard.apps.GitHubResources import GitHubResourceConflict, get_resources, refresh_resources
    from langboard_shared.domain.models import AppResourceBinding, BoardAppBinding
    from sqlalchemy import select

    service, board, connection, calls, responses = installation
    with DbSession.use(readonly=False) as db:
        own = BoardAppBinding(project_id=board[2].id, app_key="github", workflow_mapping={"active": "column"})
        foreign = BoardAppBinding(project_id=11, app_key="github")
        db.insert(own)
        db.insert(foreign)
        for binding in [own, foreign]:
            db.insert(
                AppResourceBinding(
                    board_binding_id=binding.id,
                    connection_id=connection.id,
                    resource_type="repository",
                    external_resource_id="99",
                    resource_path=[
                        {"type": "installation", "id": "17"},
                        {"type": "account", "id": "7"},
                        {"type": "repository", "id": "99"},
                    ],
                    access_state="granted",
                    health="unknown",
                )
            )
    snapshot = get_resources(service, board[1], board[2].get_uid())
    if failure == "external":
        responses["status"] = 403
    elif failure == "host_revoke":
        responses["revoke_host"] = True
    if failure in {"host_revoke", "stale"}:
        with pytest.raises(GitHubResourceConflict):
            refresh_resources(
                service,
                board[1],
                board[2].get_uid(),
                connection.get_uid(),
                "0" * 64 if failure == "stale" else snapshot["revision"],
            )
    else:
        result = refresh_resources(service, board[1], board[2].get_uid(), connection.get_uid(), snapshot["revision"])
        assert result["items"][0]["selected"]
        assert result["items"][0]["health"] == ("healthy" if failure is None else "unavailable")
        assert result["items"][0]["access_state"] == ("granted" if failure is None else "unknown")
    with DbSession.use(readonly=False) as db:
        untouched = db.exec(
            select(AppResourceBinding).where(AppResourceBinding.board_binding_id == foreign.id)
        ).first()[0]
        persisted = db.exec(select(BoardAppBinding).where(BoardAppBinding.id == own.id)).first()[0]
        assert untouched.is_selected and untouched.health == "unknown"
        assert persisted.state == "disabled" and persisted.workflow_mapping == {"active": "column"}
    if failure == "stale":
        assert not calls
