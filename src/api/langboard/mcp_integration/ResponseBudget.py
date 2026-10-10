"""Bound modern read responses without returning clipped JSON or hiding schemas."""

from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from fastmcp.tools.base import InputRequiredToolResult
from pydantic_core import to_json
from .Annotations import READ_ONLY_TOOLS


MAX_READ_RESPONSE_BYTES = 1_000_000


class ReadResponseBudgetMiddleware(Middleware):
    def __init__(self, max_bytes: int = MAX_READ_RESPONSE_BYTES):
        if type(max_bytes) is not int or max_bytes < 1_024:
            raise ValueError("Read response budget must be an integer of at least 1024 bytes")
        self.max_bytes = max_bytes

    async def on_call_tool(self, context, call_next):
        result = await call_next(context)
        if isinstance(result, InputRequiredToolResult) or not isinstance(result, ToolResult):
            return result
        name = context.message.name
        if name == "call_raw_tool":
            name = (context.message.arguments or {}).get("name")
        if not isinstance(name, str) or name not in READ_ONLY_TOOLS:
            return result
        actual_bytes = len(to_json(result, fallback=str))
        if actual_bytes <= self.max_bytes:
            return result
        return ToolResult(
            content="Read response exceeds the size budget. Reduce limit, request fewer sections, "
            "or use a narrower query and follow its continuation cursors. No partial data was returned.",
            is_error=True,
            meta={
                "response_limit": {
                    "max_bytes": self.max_bytes,
                    "actual_bytes": actual_bytes,
                    "next_action": "narrow_query",
                }
            },
        )
