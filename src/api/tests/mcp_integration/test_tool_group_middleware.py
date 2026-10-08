import asyncio
from types import SimpleNamespace
from typing import Any
import pytest
from fastmcp.exceptions import AuthorizationError
from langboard.mcp_integration.ToolGroupMiddleware import ToolGroupMiddleware
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


def test_tool_group_filters_discovery_and_blocks_ungranted_calls() -> None:
    """The native middleware applies one policy to discovery and execution."""

    group = SimpleNamespace(activated_at=object(), tools=["allowed"])
    token = mcp_auth_context.set({"tool_group": group})
    middleware = ToolGroupMiddleware()
    try:
        listed = asyncio.run(
            middleware.on_list_tools(
                SimpleNamespace(),
                lambda context: _value([SimpleNamespace(name="allowed"), SimpleNamespace(name="blocked")]),
            )
        )
        assert [tool.name for tool in listed] == ["allowed"]

        with pytest.raises(AuthorizationError, match="not allowed"):
            asyncio.run(
                middleware.on_call_tool(
                    SimpleNamespace(message=SimpleNamespace(name="blocked")),
                    lambda context: _value("called"),
                )
            )
    finally:
        mcp_auth_context.reset(token)


def test_tool_group_fails_closed_without_active_group() -> None:
    """Missing and inactive groups cannot enumerate tools."""

    token = mcp_auth_context.set(None)
    try:
        with pytest.raises(AuthorizationError, match="active MCP tool group"):
            asyncio.run(
                ToolGroupMiddleware().on_list_tools(
                    SimpleNamespace(),
                    lambda context: _value([]),
                )
            )
    finally:
        mcp_auth_context.reset(token)


async def _value(value: Any) -> Any:
    return value


@pytest.mark.parametrize("surface", ["mcp", "rest"])
@pytest.mark.parametrize(
    "case,expected",
    [
        ("oidc_default", 200),
        ("explicit", 200),
        ("explicit_wrong_owner", 403),
        ("explicit_blocked_tool", 403),
        ("empty_header", 400),
        ("native_session", 400),
        ("api_key", 400),
        ("bot", 403),
        ("unauthenticated", 401),
        ("wrong_owner", 403),
        ("inactive", 403),
        ("missing_group", 404),
        ("blocked_tool", 403),
        ("unconfigured", 400),
    ],
)
async def test_native_oidc_group_default_preserves_authorization(monkeypatch, surface, case, expected):
    from importlib import import_module
    from langboard_shared.Env import Env
    from starlette.requests import Request

    module = import_module("langboard.middlewares.McpAuthMiddleware")
    api = import_module("langboard.routes.mcp.McpApi")

    class FakeUser:
        id = 7
        is_admin = True
        email = "employee@example.test"

    user = FakeUser() if case != "bot" else object()
    monkeypatch.setattr(module, "User", FakeUser)
    monkeypatch.setattr(api, "User", FakeUser)
    monkeypatch.setattr(
        type(Env),
        "MCP_OIDC_DEFAULT_TOOL_GROUP_UID",
        property(lambda _: "" if case == "unconfigured" else "default-group"),
    )
    monkeypatch.setattr(type(Env), "PUBLIC_UI_URL", property(lambda _: "https://ui.example.test"))
    headers = []
    if case in ("explicit", "explicit_wrong_owner", "explicit_blocked_tool", "empty_header"):
        headers.append((b"x-mcp-tool-group-uid", b"" if case == "empty_header" else b"explicit-group"))
    scope = {"type": "http", "path": "/mcp/tools/allowed", "method": "POST", "headers": headers}
    claims = {"sub": "verified-user"} if case not in ("native_session", "bot", "unauthenticated") else None
    looked_up = []
    called = []
    group = SimpleNamespace(
        activated_at=None if case == "inactive" else object(),
        user_id=8 if case in ("wrong_owner", "explicit_wrong_owner") else 7,
        tools=[] if case in ("blocked_tool", "explicit_blocked_tool") else ["allowed"],
    )

    def lookup(uid):
        looked_up.append(uid)
        return None if case == "missing_group" else group

    service = SimpleNamespace(mcp_tool_group=SimpleNamespace(get_by_id_like=lookup), close=lambda: None)
    monkeypatch.setattr(module, "DomainService", lambda: service)
    monkeypatch.setattr(api, "DomainService", lambda: service)

    def validate(scope, **kwargs):
        if case == "unauthenticated":
            return 401
        scope["auth"] = user
        scope["oidc_claims"] = claims
        if case == "api_key":
            scope["api_key"] = SimpleNamespace(user_id=7)
        return user

    monkeypatch.setattr(module.MiddlewareHelper, "validate_auth", validate)

    async def receive():
        return {"type": "http.request", "body": b"{}"}

    async def native_call(name, arguments):
        called.append(name)
        return {"ok": True}

    monkeypatch.setattr(api.McpTool, "get_tool", lambda _: {"accessible_type": "user"})
    monkeypatch.setattr(api.McpServer.mcp, "call_tool", native_call)
    if surface == "rest":
        validate(scope)
        try:
            if case == "unauthenticated":
                scope.pop("auth", None)
            response = await api.execute_mcp_tool("allowed", Request(scope, receive))
            actual = response.status_code
        except Exception as error:
            actual = getattr(error, "status_code", None)
            if actual is None:
                raise
    else:
        messages = []

        async def send(message):
            messages.append(message)

        async def app(scope, receive, send):
            # Real native discovery/call gate remains authoritative after group resolution.
            from langboard.mcp_integration.ToolGroupMiddleware import ToolGroupMiddleware

            try:
                await ToolGroupMiddleware().on_call_tool(
                    SimpleNamespace(message=SimpleNamespace(name="allowed")), lambda _: native_call("allowed", {})
                )
                actual = 200
            except AuthorizationError:
                actual = 403
            await send({"type": "http.response.start", "status": actual, "headers": []})

        # Bots cannot use the OIDC default; absent group is rejected before dispatch.
        await module.McpAuthMiddleware(app)(scope, receive, send)
        actual = next(message["status"] for message in messages if message["type"] == "http.response.start")
        if case == "bot":
            expected = 400
    assert actual == expected
    if expected == 200:
        assert looked_up == ["explicit-group" if case == "explicit" else "default-group"]
        assert called == ["allowed"]
    else:
        assert called == []
