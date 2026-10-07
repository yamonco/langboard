# ruff: noqa: F811
"""Mounted extension HTTP calls retain native DB authority and per-call cleanup."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import FastMCP
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.RoleFilter import McpRoleFilter
from langboard.mcp_integration.Server import McpServer, _create_fastmcp
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.middlewares.McpAuthMiddleware import McpAuthMiddleware
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import McpRole, McpToolGroup, ProjectRole, User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper


def payload(response):
    assert response.status_code == 200, response.text
    return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize("installed", [False, True])
def test_extension_http_uses_actual_auth_roles_and_cleans_services(board, monkeypatch, installed):
    engine = DbEngine.get_main_engine()
    for model in (McpRole, McpToolGroup):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    with DbSession.use(readonly=False) as db:
        role = McpRole(user_id=board[1].id, actions=["read"])
        group = McpToolGroup(
            name="Native extension HTTP proof", tools=["extension_http_probe"], activated_at=SafeDateTime.now()
        )
        db.insert(role)
        db.insert(group)
        board[4].actions = ["read", "update"]
        db.update(board[4])
    created, closed, calls = [], [], []
    fail = [False]
    original_init, original_close = DomainService.__init__, DomainService.close

    def initialize(service):
        original_init(service)
        created.append(service)

    def close(service):
        closed.append(service)
        original_close(service)

    monkeypatch.setattr(DomainService, "__init__", initialize)
    monkeypatch.setattr(DomainService, "close", close)

    @McpTool.add("user")
    @McpRoleFilter.add(
        ProjectRole,
        ["update"],
        lambda query, arguments, user_id: query.where(
            ProjectRole.project_id == InfraHelper.convert_id(arguments["project_uid"]), ProjectRole.user_id == user_id
        ),
    )
    def extension_http_probe(project_uid: str, user: User, service: DomainService) -> dict:
        assert user.id == board[1].id and isinstance(service, DomainService)
        calls.append(project_uid)
        if fail[0]:
            raise RuntimeError("Native handler failure")
        return {"project_uid": project_uid}

    parent = _create_fastmcp()
    if installed:
        child = FastMCP("native-selected-extension", mask_error_details=True)
        child.add_provider(create_native_extension_provider(["extension_http_probe"], McpServer._wrap_tool))
        parent.mount(child)
    app = parent.http_app(path="/stream", stateless_http=True, allowed_hosts=["testserver"], allowed_origins=[])
    app.add_middleware(McpAuthMiddleware)
    access, refresh = AuthSecurity.authenticate(board[1].id)
    headers = {
        "Authorization": f"Bearer {access}",
        AuthSecurity.MCP_TOOL_GROUP_UID_HEADER: group.get_uid(),
        "Accept": "application/json, text/event-stream",
    }
    arguments = {"project_uid": board[2].get_uid()}

    def request(client, method, params=None):
        return client.post(
            "/stream",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})},
        )

    def invoke(client):
        return request(client, "tools/call", {"name": "extension_http_probe", "arguments": arguments})

    try:
        with TestClient(app) as client:
            assert client.post("/stream", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
            client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
            tools = payload(request(client, "tools/list"))["result"]["tools"]
            assert bool(tools) is installed
            if installed:
                assert (
                    "user" not in tools[0]["inputSchema"]["properties"]
                    and "service" not in tools[0]["inputSchema"]["properties"]
                )
            allowed = payload(invoke(client))
            assert bool(allowed["result"].get("isError", False)) is not installed
            assert len(calls) == int(installed)
            with DbSession.use(readonly=False) as db:
                board[4].actions = ["read"]
                db.update(board[4])
            assert payload(invoke(client))["result"]["isError"]
            assert len(calls) == int(installed)
            with DbSession.use(readonly=False) as db:
                board[4].actions = ["read", "update"]
                db.update(board[4])
                role.actions = []
                db.update(role)
            assert invoke(client).status_code == 403
            with DbSession.use(readonly=False) as db:
                role.actions = ["read"]
                db.update(role)
                group.tools = []
                db.update(group)
            assert not payload(request(client, "tools/list"))["result"]["tools"]
            assert payload(invoke(client))["result"]["isError"]
            with DbSession.use(readonly=False) as db:
                group.tools = ["extension_http_probe"]
                db.update(group)
            fail[0] = True
            assert payload(invoke(client))["result"]["isError"]
            assert len(calls) == 2 * int(installed)
        # Native REST remains usable regardless of whether the extension catalog is mounted.
        import langboard.routes.board.BoardGitHubAppApi  # noqa: F401

        rest = FastAPI()
        rest.include_router(AppRouter.api)
        rest.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
        with TestClient(rest) as client:
            client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
            response = client.get(
                f"/board/{board[2].get_uid()}/settings/apps/github/resources",
                headers={"Authorization": f"Bearer {access}"},
            )
            assert response.status_code == 200 and response.json()["items"] == []
        assert len(created) == len(closed)
        assert all(sum(instance is item for item in closed) == 1 for instance in created)
    finally:
        McpTool._tools.pop("extension_http_probe", None)
        McpRoleFilter._filtered.pop(extension_http_probe, None)
