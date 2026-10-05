"""Native connection metadata carries policy without a plugin or tool grants."""

from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.mcp_integration.AgentPolicy import AGENT_POLICY
from langboard.mcp_integration.Server import McpServer
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("profile", ["compatibility", "agent", "raw"])
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_native_handshake_delivers_policy_without_plugin(profile, mode):
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set({"tool_group": SimpleNamespace(activated_at=object(), tools=[])})
    try:
        async with Client(server, mode=mode) as client:
            assert client.protocol_version == ("2025-11-25" if mode == "legacy" else "2026-07-28")
            assert client.instructions == AGENT_POLICY
            assert "explicit user instruction" in client.instructions
            assert "Checklist completion is not approval" in client.instructions
            # Policy metadata does not bypass empty grants; raw discovery stays public.
            assert {tool.name for tool in await client.list_tools()} <= {"search_raw_tools", "call_raw_tool"}
    finally:
        mcp_auth_context.reset(token)
