# ruff: noqa: F811
"""Per-reference audit pages preserve current authority without touching secrets."""

import json
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.security import KeyVault
from langboard_shared.domain.services.factory.SecretReferenceService import SecretReferenceUnavailable
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr


def test_history_pages_no_material_with_revision_facts_and_foreign_cursor_denial(secrets, monkeypatch):
    service, board, _ = secrets
    actor = board[1]
    reference = service.create(actor, "personal", "me", "history/key", SecretStr("fixture-sensitive"))
    service.resolve_for_runtime(actor, reference["uri"])
    renamed = service.rename(actor, reference["uri"], "history/renamed", 0)
    rotated = service.rotate(actor, reference["uri"], SecretStr("replacement-sensitive"), renamed["revision"])
    other = service.create(actor, "personal", "me", "history/other", SecretStr("other-sensitive"))
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("History read vault material"))
    monkeypatch.setattr(KeyVault, "store_secret", lambda *_: pytest.fail("History wrote vault material"))
    first = service.list_audit(actor, reference["uri"], limit=2)
    assert [row["action"] for row in first["items"]] == ["rotated", "renamed"]
    assert [(row["revision_before"], row["revision_after"]) for row in first["items"]] == [(1, 2), (0, 1)]
    second = service.list_audit(actor, reference["uri"], limit=2, cursor=first["next_cursor"])
    assert [row["action"] for row in second["items"]] == ["resolved", "created"]
    assert second["items"][0]["revision_before"] == 0 and second["items"][1]["revision_before"] is None
    assert second["next_cursor"] is None
    assert not set(row["uid"] for row in first["items"]) & set(row["uid"] for row in second["items"])
    assert not any(
        word in json.dumps([first, second]) for word in ["sensitive", "locator", "provider", "source_uid", "scope_id"]
    )
    foreign_cursor = service.list_audit(actor, other["uri"])["items"][0]["uid"]
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=foreign_cursor)
    assert rotated["revision"] == 2
    with DbSession.use(readonly=False) as db:
        actor.activated_at = None
        db.update(actor)
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=first["next_cursor"])


def test_history_rechecks_moved_reference_and_role_before_next_page(secrets):
    service, board, _ = secrets
    actor = board[1]
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    reference = service.create(actor, "project", board[2].get_uid(), "history/board", SecretStr("fixture-sensitive"))
    service.resolve_for_runtime(actor, reference["uri"])
    first = service.list_audit(actor, reference["uri"], limit=1)
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read"]
        db.update(board[4])
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(actor, reference["uri"], cursor=first["next_cursor"])
    with pytest.raises(SecretReferenceUnavailable):
        service.list_audit(board[3], reference["uri"])
    with pytest.raises(ValueError):
        service.list_audit(actor, reference["uri"], limit=51)


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_native_authenticated_history_http_and_current_revocation(secrets, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.account.SecretReferenceApi import get_secret_reference_history
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/http", SecretStr("fixture-sensitive"))
    wrapper = SimpleNamespace(secret_reference=service, close=lambda: None)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: wrapper
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is get_secret_reference_history:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: wrapper
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    url = "/secret-references/" + meta["uri"].rsplit("/", 1)[1] + "/history"
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        headers = {"Authorization": f"Bearer {access}"}
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and response.json()["items"][0]["action"] == "created"
        assert response.headers["cache-control"] == "no-store"
        assert "fixture-sensitive" not in response.text
        with DbSession.use(readonly=False) as db:
            actor.activated_at = None
            db.update(actor)
        assert client.get(url, headers=headers).status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_fastmcp_history_schema_and_no_vault_reads(secrets, monkeypatch):
    from fastmcp import Client, FastMCP
    from langboard.mcp_integration.Extensions import create_native_extension_provider
    from langboard.mcp_integration.Server import McpServer
    from langboard.mcp_tools.SecretReferenceMcp import list_secret_reference_history
    from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
    from langboard_shared.domain.services import DomainService

    service, board, _ = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "history/mcp", SecretStr("fixture-sensitive"))
    monkeypatch.setattr(DomainService, "secret_reference", property(lambda _: service))
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("MCP history resolved material"))
    server = FastMCP("secret-history")
    server.add_provider(
        create_native_extension_provider([list_secret_reference_history.__name__], McpServer._wrap_tool)
    )
    token = mcp_auth_context.set({"user_or_bot": actor})
    try:
        async with Client(server) as client:
            tool = (await client.list_tools())[0]
            assert tool.annotations.readOnlyHint
            assert set(tool.inputSchema["properties"]) == {"uri", "limit", "cursor"}
            result = (await client.call_tool(tool.name, {"uri": meta["uri"], "limit": 1})).structured_content
            assert result["items"][0]["action"] == "created"
            assert "fixture-sensitive" not in json.dumps(result)
    finally:
        mcp_auth_context.reset(token)
