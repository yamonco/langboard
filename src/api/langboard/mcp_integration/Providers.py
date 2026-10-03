"""FastMCP provider adapter for the existing native domain registry."""

from collections.abc import Callable
from typing import Any
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.tools import Tool
from .Tool import McpTool


def create_compatibility_provider(wrap_tool: Callable[[str, Callable[..., Any]], Callable[..., Any]]) -> LocalProvider:
    """Preserve legacy names and domain wrappers while using native providers."""
    provider = LocalProvider(on_duplicate="error")
    for name, metadata in McpTool.get_tools().items():
        provider.add_tool(
            Tool.from_function(wrap_tool(name, metadata["handler"]), name=name, description=metadata["description"])
        )
    return provider
