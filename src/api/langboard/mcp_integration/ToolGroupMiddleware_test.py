import asyncio
from types import SimpleNamespace
from typing import Any
import pytest
from fastmcp.exceptions import AuthorizationError
from ..middlewares.McpAuthMiddleware import mcp_auth_context
from .ToolGroupMiddleware import ToolGroupMiddleware


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
