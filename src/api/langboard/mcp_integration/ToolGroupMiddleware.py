from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import Tool
from mcp_types import CallToolRequestParams, ListToolsRequest
from ..middlewares.McpAuthMiddleware import mcp_auth_context


class ToolGroupMiddleware(Middleware):
    """Expose and execute only tools granted to the authenticated tool group."""

    async def on_list_tools(
        self,
        context: MiddlewareContext[ListToolsRequest],
        call_next: Callable[[MiddlewareContext[ListToolsRequest]], Awaitable[Sequence[Tool]]],
    ) -> Sequence[Tool]:
        """Filter discovery through the validated Langboard tool group."""

        allowed = self._allowed_tools()
        return [tool for tool in await call_next(context) if tool.name in allowed]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: Callable[[MiddlewareContext[CallToolRequestParams]], Awaitable[Any]],
    ) -> Any:
        """Reject calls that are outside the validated Langboard tool group."""

        if context.message.name not in self._allowed_tools():
            raise AuthorizationError(f"Tool '{context.message.name}' is not allowed")
        return await call_next(context)

    @staticmethod
    def _allowed_tools() -> set[str]:
        auth_data = mcp_auth_context.get()
        tool_group = auth_data.get("tool_group") if auth_data else None
        if tool_group is None or tool_group.activated_at is None:
            raise AuthorizationError("An active MCP tool group is required")
        return set(tool_group.tools)
