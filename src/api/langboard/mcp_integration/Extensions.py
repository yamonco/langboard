"""Explicit host-owned extensions select native commands without installing handlers."""

from collections.abc import Callable, Sequence
from fastmcp.server.providers.local_provider import LocalProvider
from .Providers import create_native_tool
from .Tool import McpTool


def create_native_extension_provider(
    commands: Sequence[str], wrap_tool: Callable, *, modern_annotations: bool = True
) -> LocalProvider:
    """Build an isolated command catalog through the host's existing execution boundary.

    No plugin handler, actor, role policy or repository is accepted. The host must
    use its native wrapper and authenticated middleware for each mounted catalog.
    This is composition of trusted native commands, not a Python code sandbox.
    """
    names = tuple(commands)
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("An extension requires explicit native command names")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate extension command")
    metadata = [(name, McpTool.get_tool(name)) for name in names]
    if any(data is None for _, data in metadata):
        raise ValueError("Unknown native extension command")
    provider = LocalProvider(on_duplicate="error")
    for name, data in metadata:
        provider.add_tool(create_native_tool(name, data, wrap_tool, modern_annotations=modern_annotations))
    return provider
