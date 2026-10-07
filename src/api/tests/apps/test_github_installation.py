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
        if request.url.path.startswith("/app/installations/"):
            claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], issuer="42")
            assert claims["exp"] - claims["iat"] <= 600
        else:
            assert token == "fixture-ephemeral-token"
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
    snapshot = get_resources(service, board[1], board[2].get_uid())
    added = update_resources(
        service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99, 100), (), snapshot["revision"]
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
        service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99,), (), removed["revision"]
    )
    assert len(restored["items"]) == 2 and all(item["selected"] for item in restored["items"])


@pytest.mark.parametrize("returned_ids", [[99], [99, 101], [99, 100, 100]])
def test_resource_delta_rejects_incomplete_wrong_or_duplicate_external_set(installation, returned_ids):
    from langboard.apps.GitHubResources import get_resources, update_resources

    service, board, connection, calls, responses = installation
    snapshot = get_resources(service, board[1], board[2].get_uid())
    responses["returned_ids"] = returned_ids
    with pytest.raises(github.GitHubManifestUnavailable):
        update_resources(
            service, board[1], board[2].get_uid(), connection.get_uid(), 17, 7, (99, 100), (), snapshot["revision"]
        )
    assert get_resources(service, board[1], board[2].get_uid()) == snapshot
    assert calls[-1].method == "DELETE"
