"""Extension catalogs reuse current native authority and per-call resource cleanup."""

from unittest.mock import Mock
import pytest
from fastmcp import Client, FastMCP
from langboard.Loader import ModuleLoader
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.Providers import create_native_domain_provider
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import User
from langboard_shared.domain.services import DomainService


@pytest.mark.asyncio
async def test_explicit_catalog_has_identical_native_schema_and_does_not_mutate_registry():
    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    before = dict(McpTool.get_tools())
    core = FastMCP("core")
    core.add_provider(create_native_domain_provider(McpServer._wrap_tool, modern_annotations=True))
    extension = FastMCP("extension")
    extension.add_provider(create_native_extension_provider(["get_card_bundle"], McpServer._wrap_tool))
    async with Client(core) as a, Client(extension) as b:
        native = {tool.name: tool for tool in await a.list_tools()}["get_card_bundle"]
        selected = await b.list_tools()
        assert len(selected) == 1
        assert selected[0].inputSchema == native.inputSchema
        assert selected[0].outputSchema == native.outputSchema
        assert selected[0].annotations == native.annotations
        for key in ("user", "repository", "service", "roles"):
            assert key not in selected[0].inputSchema["properties"]
    assert McpTool.get_tools() == before


@pytest.mark.parametrize("commands", [[], ["get_card_bundle", "get_card_bundle"], ["missing_command"], [None]])
def test_invalid_registration_leaves_native_registry_unchanged(commands):
    before = dict(McpTool.get_tools())
    with pytest.raises(ValueError):
        create_native_extension_provider(commands, McpServer._wrap_tool)
    assert McpTool.get_tools() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_host_role_revocation_and_injected_service_cleanup(monkeypatch, fail):
    closed = Mock()
    body = Mock()
    granted = [True]

    def extension_native_contract(project_uid: str, user: User, service: DomainService):
        assert user is actor
        body(project_uid)
        if fail:
            raise RuntimeError("native failure")
        return {"project_uid": project_uid}

    actor = User(
        id=1,
        firstname="Fixture",
        lastname="Actor",
        username="fixture",
        email="fixture@example.invalid",
        password="fixture-only",
    )
    McpTool.add("user")(extension_native_contract)
    monkeypatch.setattr(DomainService, "close", lambda self: closed())
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: granted[0])
    server = FastMCP("extension")
    server.add_provider(create_native_extension_provider(["extension_native_contract"], McpServer._wrap_tool))
    token = mcp_auth_context.set({"user_or_bot": actor})
    try:
        async with Client(server) as client:
            first = await client.call_tool("extension_native_contract", {"project_uid": "p"}, raise_on_error=False)
            assert first.is_error is fail
            assert body.call_count == 1
            assert closed.call_count == 1
            granted[0] = False
            denied = await client.call_tool("extension_native_contract", {"project_uid": "p"}, raise_on_error=False)
            assert denied.is_error
            assert body.call_count == closed.call_count == 1
    finally:
        mcp_auth_context.reset(token)
        McpTool._tools.pop("extension_native_contract", None)
