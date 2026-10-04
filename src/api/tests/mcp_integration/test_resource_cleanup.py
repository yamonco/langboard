"""Invocation-owned resources are released even when another release fails."""

from types import SimpleNamespace
import pytest
from langboard.mcp_integration.Server import McpServer
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("failure", ["handler", "injection", "cleanup"])
async def test_every_created_resource_is_closed_after_failure(monkeypatch, failure):
    closed = []
    created = []

    def close(name):
        closed.append(name)
        if failure == "cleanup" and name == "second":
            raise RuntimeError("cleanup failure")

    def inject(name, parameter, actor, kwargs):
        if failure == "injection" and name == "second":
            raise RuntimeError("injection failure")
        created.append(name)
        return {**kwargs, name: object()}, SimpleNamespace(close=lambda: close(name))

    async def handler(first: int, second: int):
        if failure == "handler":
            raise RuntimeError("handler failure")
        return {"ok": True}

    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    monkeypatch.setattr(McpServer, "_inject_kwargs", inject)
    token = mcp_auth_context.set({"user_or_bot": object()})
    try:
        with pytest.raises(RuntimeError, match=f"{failure} failure"):
            await McpServer._wrap_tool("test_cleanup", handler)()
        assert closed == list(reversed(created))
    finally:
        mcp_auth_context.reset(token)
