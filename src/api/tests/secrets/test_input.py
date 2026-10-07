# ruff: noqa: F811
"""Native vault persistence and one-use cache boundary; no material on MCP outputs."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from langboard.mcp_tools.SecretReferenceMcp import (
    get_secret_input_status,
    request_secret_input,
    request_secret_rotation_input,
)
from langboard.secrets import SecretInput as input_flow
from langboard_shared.core.caching import Cache
from langboard_shared.core.caching.InMemoryCache import InMemoryCache
from langboard_shared.core.db import DbSession
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from pydantic import SecretStr


@pytest.fixture
def flow(secrets, monkeypatch, tmp_path):
    secret_service, board, path = secrets
    monkeypatch.setattr(type(Env), "CACHE_DIR", property(lambda _: tmp_path / "input-cache"))
    monkeypatch.setattr(Cache, "_cache", InMemoryCache())
    monkeypatch.setattr(type(Env), "PUBLIC_UI_URL", property(lambda _: "https://langboard.example"))
    return SimpleNamespace(secret_reference=secret_service), board[1], board


def test_one_use_secret_stays_outside_mcp_and_metadata(flow):
    service, actor, _ = flow
    pending = request_secret_input("personal", "me", "provider/api-key", actor, service)
    uid = pending["input_uid"]
    assert pending["input_url"] == "https://langboard.example/secret-input/" + uid
    assert get_secret_input_status(uid, actor, service) == {"state": "pending"}
    details, challenge = input_flow.open_input(service, actor, uid)
    assert details == {"name": "provider/api-key", "scope": "personal", "operation": "create"}
    result = input_flow.complete_input(service, actor, uid, SecretStr("fixture-secret"), challenge)
    assert result == get_secret_input_status(uid, actor, service)
    assert result["state"] == "completed"
    assert (
        service.secret_reference.resolve_for_runtime(actor, result["secret_ref"]).get_secret_value() == "fixture-secret"
    )
    assert "fixture-secret" not in json.dumps([pending, details, result, Cache.get(input_flow._key(uid))])
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, uid, SecretStr("replay"), challenge)
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.open_input(service, actor, uid)


@pytest.mark.parametrize("failure", ["other-user", "expired", "inactive", "csrf"])
def test_current_identity_expiration_and_browser_proof_fail_closed(flow, failure):
    service, actor, board = flow
    pending = input_flow.begin_input(service, actor, "personal", "me", "provider/key")
    uid = pending["input_uid"]
    _, challenge = input_flow.open_input(service, actor, uid)
    if failure == "other-user":
        actor = board[3]
    elif failure == "expired":
        Cache.set(input_flow._key(uid), Cache.get(input_flow._key(uid)), -1)
    elif failure == "inactive":
        with DbSession.use(readonly=False) as db:
            actor.activated_at = None
            db.update(actor)
    else:
        challenge = "x" * 43
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, uid, SecretStr("must-not-save"), challenge)


def test_revoked_project_permission_blocks_completion(flow):
    service, actor, board = flow
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    pending = input_flow.begin_input(service, actor, "project", board[2].get_uid(), "provider/key")
    _, challenge = input_flow.open_input(service, actor, pending["input_uid"])
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read"]
        db.update(board[4])
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, pending["input_uid"], SecretStr("must-not-save"), challenge)


def test_atomic_claim_and_ambiguous_failure_are_consumed(flow, monkeypatch):
    service, actor, _ = flow
    pending = input_flow.begin_input(service, actor, "personal", "me", "provider/key")
    uid = pending["input_uid"]
    _, challenge = input_flow.open_input(service, actor, uid)
    # Exercise the actual cache's cross-thread atomic primitive.
    with ThreadPoolExecutor(max_workers=4) as executor:
        claimed = list(executor.map(lambda _: Cache.set_if_absent(input_flow._key(uid) + ":race", True, 600), range(4)))
    assert sum(claimed) == 1
    monkeypatch.setattr(
        service.secret_reference, "create", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret leak"))
    )
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, uid, SecretStr("fixture-secret"), challenge)
    assert input_flow.input_status(service, actor, uid) == {"state": "failed"}
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, uid, SecretStr("replay"), challenge)


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_authenticated_browser_transport_never_echoes_invalid_material(flow, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.account.SecretInputApi import open_secret_input, submit_secret_input
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity

    service, actor, _ = flow
    service.close = lambda: None
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) in {open_secret_input, submit_secret_input}:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    from langboard.middlewares.GZipDecompressMiddleware import GZipDecompressMiddleware

    app.add_middleware(GZipDecompressMiddleware)
    access, refresh = AuthSecurity.authenticate(actor.id)
    headers = {"Authorization": f"Bearer {access}", "Origin": "https://langboard.example"}
    uid = input_flow.begin_input(service, actor, "personal", "me", "provider/http")["input_uid"]
    url = "/secret-input/" + uid
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        opened = client.get(url, headers=headers)
        assert opened.status_code == 200
        import gzip

        middleware = importlib.import_module("langboard.middlewares.GZipDecompressMiddleware")
        monkeypatch.setattr(middleware, "TemporaryFile", lambda: pytest.fail("Secret body reached disk spool"))
        compressed = client.post(
            url,
            content=gzip.compress(b'{"value":"fixture-sensitive"}'),
            headers={**headers, "Content-Encoding": "gzip", "Content-Type": "application/json"},
        )
        assert compressed.status_code == 400 and "fixture-sensitive" not in compressed.text
        assert opened.headers["cache-control"] == "no-store"
        assert "HttpOnly" in opened.headers["set-cookie"]
        for body in [{"value": {"fixture-sensitive": "bad"}}, {"value": "fixture-sensitive", "extra": True}]:
            response = client.post(url, json=body, headers=headers)
            assert response.status_code == 400 and "fixture-sensitive" not in response.text
        assert (
            client.post(
                url, json={"value": "fixture-sensitive"}, headers={**headers, "Origin": "https://evil.invalid"}
            ).status_code
            == 400
        )
        response = client.post(url, json={"value": "fixture-sensitive"}, headers=headers)
        assert response.status_code == 200 and "fixture-sensitive" not in response.text
        assert response.json()["state"] == "completed"
        assert client.post(url, json={"value": "replay"}, headers=headers).status_code == 400


@pytest.mark.asyncio
async def test_fastmcp_input_schema_contains_no_material_and_returns_reference(flow, monkeypatch):
    from fastmcp import Client, FastMCP
    from langboard.mcp_integration.Extensions import create_native_extension_provider
    from langboard.mcp_integration.Server import McpServer
    from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
    from langboard_shared.domain.services import DomainService

    service, actor, _ = flow
    monkeypatch.setattr(DomainService, "secret_reference", property(lambda _: service.secret_reference))
    server = FastMCP("secret-input")
    server.add_provider(
        create_native_extension_provider(
            [request_secret_input.__name__, request_secret_rotation_input.__name__, get_secret_input_status.__name__],
            McpServer._wrap_tool,
        )
    )
    token = mcp_auth_context.set({"user_or_bot": actor})
    try:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools["request_secret_input"].inputSchema["properties"]) == {"scope", "scope_uid", "name"}
            assert not tools["request_secret_input"].annotations.readOnlyHint
            assert tools["get_secret_input_status"].annotations.readOnlyHint
            pending = (
                await client.call_tool(
                    "request_secret_input", {"scope": "personal", "scope_uid": "me", "name": "provider/mcp"}
                )
            ).structured_content
            _, challenge = input_flow.open_input(service, actor, pending["input_uid"])
            input_flow.complete_input(service, actor, pending["input_uid"], SecretStr("fixture-sensitive"), challenge)
            result = (
                await client.call_tool("get_secret_input_status", {"input_uid": pending["input_uid"]})
            ).structured_content
            assert result["state"] == "completed" and result["secret_ref"].startswith("secret://ref/")
            assert "fixture-sensitive" not in json.dumps(result)
            assert set(tools["request_secret_rotation_input"].inputSchema["properties"]) == {"uri", "expected_revision"}
            rotation = (
                await client.call_tool(
                    "request_secret_rotation_input", {"uri": result["secret_ref"], "expected_revision": 0}
                )
            ).structured_content
            details, challenge = input_flow.open_input(service, actor, rotation["input_uid"])
            assert details["operation"] == "rotate"
            input_flow.complete_input(service, actor, rotation["input_uid"], SecretStr("rotated-fixture"), challenge)
            rotated = (
                await client.call_tool("get_secret_input_status", {"input_uid": rotation["input_uid"]})
            ).structured_content
            assert rotated == result and "rotated-fixture" not in json.dumps(rotated)
    finally:
        mcp_auth_context.reset(token)


def test_cancel_consumes_input_without_secret_storage(flow):
    service, actor, _ = flow
    pending = input_flow.begin_input(service, actor, "personal", "me", "provider/cancel")
    _, challenge = input_flow.open_input(service, actor, pending["input_uid"])
    assert input_flow.cancel_input(service, actor, pending["input_uid"]) == {"state": "cancelled"}
    assert input_flow.input_status(service, actor, pending["input_uid"]) == {"state": "cancelled"}
    with pytest.raises(SecretReferenceUnavailable):
        input_flow.complete_input(service, actor, pending["input_uid"], SecretStr("never-save"), challenge)


def test_expired_tombstone_reports_state_without_accepting_or_extending_input(flow, monkeypatch):
    service, actor, _ = flow
    pending = input_flow.begin_input(service, actor, "personal", "me", "provider/expiry")
    uid = pending["input_uid"]
    _, challenge = input_flow.open_input(service, actor, uid)
    expiry = Cache.get(input_flow._key(uid))["expires_at"]
    monkeypatch.setattr(input_flow, "time", lambda: expiry)
    assert input_flow.input_status(service, actor, uid) == {"state": "expired"}
    for action in [
        lambda: input_flow.open_input(service, actor, uid),
        lambda: input_flow.cancel_input(service, actor, uid),
        lambda: input_flow.complete_input(service, actor, uid, SecretStr("never-save"), challenge),
    ]:
        with pytest.raises(SecretReferenceUnavailable):
            action()
    assert Cache.get(input_flow._key(uid))["expires_at"] == expiry


@pytest.mark.parametrize("change", ["none", "renamed", "revoked", "rotated"])
def test_rotation_fixed_reference_revision_and_old_material_retention(flow, change):
    from langboard.mcp_tools.SecretReferenceMcp import request_secret_rotation_input

    service, actor, _ = flow
    reference = service.secret_reference.create(actor, "personal", "me", "provider/rotate", SecretStr("old-secret"))
    pending = request_secret_rotation_input(reference["uri"], reference["revision"], actor, service)
    uid = pending["input_uid"]
    details, challenge = input_flow.open_input(service, actor, uid)
    assert details["operation"] == "rotate"
    if change == "renamed":
        service.secret_reference.rename(actor, reference["uri"], "provider/renamed", reference["revision"])
    elif change == "revoked":
        service.secret_reference.revoke(actor, reference["uri"], reference["revision"])
    elif change == "rotated":
        service.secret_reference.rotate(actor, reference["uri"], SecretStr("other-secret"), reference["revision"])
    if change == "none":
        completed = input_flow.complete_input(service, actor, uid, SecretStr("new-secret"), challenge)
        assert completed == {"state": "completed", "secret_ref": reference["uri"]}
        assert service.secret_reference.get_metadata(actor, reference["uri"])["revision"] == 1
        assert service.secret_reference.resolve_for_runtime(actor, reference["uri"]).get_secret_value() == "new-secret"
    else:
        with pytest.raises(SecretReferenceUnavailable):
            input_flow.complete_input(service, actor, uid, SecretStr("must-not-save"), challenge)
        if change != "revoked":
            assert service.secret_reference.resolve_for_runtime(actor, reference["uri"]).get_secret_value() == (
                "other-secret" if change == "rotated" else "old-secret"
            )
    assert "new-secret" not in json.dumps(Cache.get(input_flow._key(uid)))
