"""Payload-free tool execution records through FastMCP's native middleware."""

import json
import logging
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.middleware import Middleware
from .Tool import McpTool


logger = logging.getLogger("langboard.mcp.telemetry")
_recording = ContextVar("mcp_telemetry_recording", default=False)


class ToolTelemetryMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        if _recording.get():
            return await call_next(context)
        token = _recording.set(True)
        name = context.message.name
        if name == "call_raw_tool":
            name = (context.message.arguments or {}).get("name")
        # Never log a caller-controlled unknown tool name or arbitrary arguments.
        tool = name if isinstance(name, str) and (McpTool.get_tool(name) or name == "search_raw_tools") else "unknown"
        request_id = uuid4().hex
        outcome = "error"
        started = perf_counter()
        try:
            result = await call_next(context)
            receipt = (result.meta or {}).get("mutation_receipt")
            if isinstance(receipt, dict):
                identity = receipt.get("request_id")
                if isinstance(identity, str) and len(identity) == 32 and all(c in "0123456789abcdef" for c in identity):
                    request_id = identity
                declared = receipt.get("outcome")
                if isinstance(declared, str) and declared in {"applied", "not_applied", "unknown"}:
                    outcome = declared
                else:
                    outcome = "error" if result.is_error else "success"
            else:
                outcome = "error" if result.is_error else "success"
            return result
        except AuthorizationError:
            outcome = "denied"
            raise
        finally:
            _recording.reset(token)
            logger.info(
                json.dumps(
                    {
                        "event": "mcp_tool_execution",
                        "request_id": request_id,
                        "tool": tool,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        "outcome": outcome,
                    },
                    separators=(",", ":"),
                )
            )
