# ruff: noqa: F811
"""Standalone SDK consumes native and selected catalogs with current DB authority."""

import pytest
from fastmcp import Client
from langboard.Loader import ModuleLoader
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.Providers import create_native_domain_provider
from langboard.mcp_integration.Server import McpServer, _create_fastmcp
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_sdk import LangboardClient, McpTransport
from langboard_sdk.mcp import NativeCommandError
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import McpToolGroup
from langboard_shared.domain.services import DomainService
from test_connection_context import prepare
from test_github_installation import board, installation, secrets  # noqa: F401
from test_github_lifecycle import lifecycle  # noqa: F401
from test_github_signal import signal_storage  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [False, True])
async def test_sdk_reads_current_resources_and_revocation_through_native_catalog(
    signal_storage, monkeypatch, extension
):
    _, actor, project_uid = prepare(signal_storage, "dokploy")
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    created, closed = [], []
    original_init, original_close = DomainService.__init__, DomainService.close

    def initialize(service):
        original_init(service)
        created.append(service)

    def close(service):
        closed.append(service)
        original_close(service)

    monkeypatch.setattr(DomainService, "__init__", initialize)
    monkeypatch.setattr(DomainService, "close", close)
    server = _create_fastmcp()
    provider = (
        create_native_extension_provider(["get_connection_context"], McpServer._wrap_tool)
        if extension
        else create_native_domain_provider(McpServer._wrap_tool, modern_annotations=True)
    )
    server.add_provider(provider)
    group = McpToolGroup(name="SDK integration fixture", tools=["get_connection_context"], activated_at=SafeDateTime.now())
    token = mcp_auth_context.set({"user_or_bot": actor, "tool_group": group})
    try:
        async with Client(server) as session:
            client = LangboardClient(McpTransport(session))
            result = await client.get_connection_context(project_uid)
            assert len(result["resources"]["items"]) == 1
            resource = result["resources"]["items"][0]
            assert resource["connection_uid"] == signal_storage[2].get_uid()
            assert resource["resource_uid"] == signal_storage[4].get_uid()
            assert "credential" not in str(result) and "secret://" not in str(result)
            group.tools = []
            with pytest.raises(NativeCommandError):
                await client.get_connection_context(project_uid)
            group.tools = ["get_connection_context"]
            with DbSession.use(readonly=False) as db:
                signal_storage[4].is_selected = False
                db.update(signal_storage[4])
            assert (await client.get_connection_context(project_uid))["resources"]["items"] == []
            with DbSession.use(readonly=False) as db:
                signal_storage[4].is_selected = True
                db.update(signal_storage[4])
                db.delete(signal_storage[1][3])
            with pytest.raises(NativeCommandError):
                await client.get_connection_context(project_uid)
        assert created
        assert len(created) == len(closed)
        assert all(sum(instance is item for item in closed) == 1 for instance in created)
    finally:
        mcp_auth_context.reset(token)
