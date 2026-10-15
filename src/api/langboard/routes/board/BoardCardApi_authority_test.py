"""Card creation and editing must honor their separate board permissions."""

import asyncio
import pytest
from langboard.mcp_tools import CardMcp
from langboard.mcp_tools.RoleChecker import McpRoleChecker
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board import BoardCardApi  # noqa: F401 - register the real HTTP routes
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.security import RoleSecurity


@pytest.mark.parametrize(
    "method,path,actions,expected",
    [
        ("POST", "/board/project-a/card", ["card_write"], 200),
        ("POST", "/board/project-a/card", ["read", "card_write"], 200),
        ("POST", "/board/project-a/card", ["card_update"], 403),
        ("POST", "/board/project-a/card", ["read"], 403),
        ("POST", "/board/project-a/card", [], 403),
        ("POST", "/board/project-a/card", ["*"], 200),
        ("PUT", "/board/project-a/card/card-a/details", ["card_update"], 200),
        ("PUT", "/board/project-a/card/card-a/details", ["card_write"], 403),
        ("PUT", "/board/project-a/card/card-a/details", ["read"], 403),
    ],
)
def test_http_card_authority(monkeypatch, method, path, actions, expected):
    checks = []
    role = ProjectRole(actions=actions)

    def decision(self, user_id, path_params, required, finder):
        checks.append((self._model_class, user_id, path_params))
        return role.is_granted(required)

    monkeypatch.setattr(RoleSecurity, "is_authorized", decision)
    actor = User(
        id=SnowflakeID(1), firstname="External", lastname="Test", email="card@example.invalid", password="test-only"
    )
    status, reached = _request(method, path, actor)
    assert status == expected
    assert reached is (expected == 200)
    assert len(checks) == 1
    assert checks[0][:2] == (ProjectRole, actor.id)
    assert checks[0][2]["project_uid"] == "project-a"


def test_card_creation_without_identity_never_reaches_command():
    assert _request("POST", "/board/project-a/card", None) == (401, False)


@pytest.mark.parametrize("handler", [CardMcp.create_card, CardMcp.create_card_in_leftmost_column])
@pytest.mark.parametrize(
    "actions,expected", [(["card_write"], True), (["card_update"], False), (["read"], False), (["*"], True)]
)
def test_mcp_creation_uses_the_same_authority(monkeypatch, handler, actions, expected):
    role = ProjectRole(actions=actions)
    checks = []

    def decision(self, user_id, arguments, required, finder):
        checks.append((self._model_class, arguments))
        return role.is_granted(required)

    monkeypatch.setattr(RoleSecurity, "is_authorized", decision)
    actor = User(
        id=SnowflakeID(1), firstname="External", lastname="Test", email="card@example.invalid", password="test-only"
    )
    assert McpRoleChecker(None).check_permission(handler, actor, {"project_uid": "project-a"}) is expected
    assert checks == [(ProjectRole, {"project_uid": "project-a"})]


def _request(method, path, actor):
    messages = []
    reached = False

    async def terminal(scope, receive, send):
        nonlocal reached
        reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": [], "query_string": b""}
    if actor is not None:
        scope["auth"] = actor
    asyncio.run(RoleMiddleware(terminal, AppRouter.api.routes)(scope, receive, send))
    return next(message["status"] for message in messages if message["type"] == "http.response.start"), reached
