# ruff: noqa: F811
"""Authenticated transports expose metadata, never secret resolution."""

import importlib
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_tools.SecretReferenceMcp import get_secret_reference_metadata as mcp_metadata
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard.routes.account.SecretReferenceApi import get_secret_reference_metadata
from langboard_shared.core.caching import Cache
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity, KeyVault
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from pydantic import SecretStr


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_http_current_auth_metadata_redaction_and_revocation(secrets, monkeypatch):
    secret_service, board, path = secrets
    meta = secret_service.create(board[1], "personal", "me", "github/key", SecretStr("fixture-sensitive-key"))
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(Cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(Cache, "set", lambda *a, **k: None)
    service = SimpleNamespace(secret_reference=secret_service, close=lambda: None)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is get_secret_reference_metadata:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {"Authorization": f"Bearer {access}"}
    url = "/secret-references/" + meta["uri"].rsplit("/", 1)[1]
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and response.json() == {"reference": meta}
        assert not any(part in response.text for part in ["fixture-sensitive-key", "locator", "provider"])
        assert client.get("/secret-references/notvalid-uid", headers=headers).status_code == 404
        with DbSession.use(readonly=False) as db:
            board[1].activated_at = None
            db.update(board[1])
        assert client.get(url, headers=headers).status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_fastmcp_metadata_schema_and_current_project_authority(secrets, monkeypatch):
    secret_service, board, path = secrets
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    meta = secret_service.create(
        board[1], "project", board[2].get_uid(), "github/key", SecretStr("fixture-sensitive-key")
    )
    monkeypatch.setattr(DomainService, "secret_reference", property(lambda _: secret_service))
    # Metadata must not even touch the vault backend.
    monkeypatch.setattr(KeyVault, "get_key", lambda *_: pytest.fail("Metadata resolved credential"))
    server = FastMCP("secret-metadata")
    server.add_provider(create_native_extension_provider([mcp_metadata.__name__], McpServer._wrap_tool))
    token = mcp_auth_context.set({"user_or_bot": board[1]})
    try:
        async with Client(server) as client:
            tools = await client.list_tools()
            assert len(tools) == 1 and tools[0].annotations.readOnlyHint
            assert set(tools[0].inputSchema["properties"]) == {"uri"}
            result = await client.call_tool(mcp_metadata.__name__, {"uri": meta["uri"]})
            assert result.structured_content == {"reference": meta}
            assert "fixture-sensitive-key" not in json.dumps(result.structured_content)
            with DbSession.use(readonly=False) as db:
                board[4].actions = ["read"]
                db.update(board[4])
            denied = await client.call_tool(mcp_metadata.__name__, {"uri": meta["uri"]}, raise_on_error=False)
            assert denied.is_error
    finally:
        mcp_auth_context.reset(token)
