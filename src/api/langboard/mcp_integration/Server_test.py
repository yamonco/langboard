from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from ..middlewares.McpAuthMiddleware import mcp_auth_context
from .Server import _create_fastmcp, _get_transport_security_allowlists, _reject_global_wildcards


def test_transport_allowlists_remain_bounded() -> None:
    """FastMCP host protection never receives a global wildcard."""

    hosts, origins = _get_transport_security_allowlists()
    assert hosts
    assert origins
    assert not {"*", "http://*", "https://*"}.intersection(hosts + origins)


@pytest.mark.parametrize("value", ["*", "http://*", "https://*"])
def test_transport_global_wildcard_is_rejected(value: str) -> None:
    """Unsafe operator overrides fail closed."""

    with pytest.raises(ValueError, match="global wildcard"):
        _reject_global_wildcards([value], "MCP_ALLOWED_HOSTS")


@pytest.mark.parametrize(("mode", "expected_version"), [("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")])
async def test_fastmcp_serves_legacy_and_modern_protocols(mode: str, expected_version: str) -> None:
    """One bounded server supports current agents and legacy ContextForge clients."""

    server = _create_fastmcp()

    @server.tool
    def add(a: int, b: int) -> dict[str, int]:
        return {"total": a + b}

    token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=["add"])})
    try:
        async with Client(server, mode=mode) as client:
            assert client.protocol_version == expected_version
            assert [tool.name for tool in await client.list_tools()] == ["add"]
            result = await client.call_tool("add", {"a": 1, "b": 2})
            assert result.structured_content == {"total": 3}
    finally:
        mcp_auth_context.reset(token)


async def test_fastmcp_rejects_invalid_arguments_before_handler() -> None:
    """Schema validation is owned by FastMCP rather than handwritten dispatch code."""

    server = _create_fastmcp()
    called = False

    @server.tool
    def record(value: int) -> dict[str, int]:
        nonlocal called
        called = True
        return {"value": value}

    token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=["record"])})
    try:
        async with Client(server, mode="2026-07-28") as client:
            with pytest.raises(ToolError, match="valid integer"):
                await client.call_tool("record", {"value": "not-an-integer"})
            assert called is False
    finally:
        mcp_auth_context.reset(token)
