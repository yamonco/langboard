# ruff: noqa: F811
"""MCP handlers use native visibility and the same persisted selection/CAS authority."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langboard.mcp_integration import McpTool
from langboard.mcp_integration.Annotations import tool_annotations
from langboard.mcp_integration.Providers import create_native_domain_provider
from langboard.mcp_integration.Server import McpServer, _create_fastmcp
from langboard.mcp_tools.CardAppResourcesMcp import get_card_app_resources, set_card_app_resource_selection
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import EmployeeMembershipPolicy, McpToolGroup
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_card_app_resources import prepare


def test_resource_tools_schema_bounds_and_human_only():
    read = McpTool.get_tool("get_card_app_resources")
    write = McpTool.get_tool("set_card_app_resource_selection")
    assert read["accessible_type"] == write["accessible_type"] == "user"
    properties = write["input_schema"]["properties"]
    assert not {"user", "service"}.intersection(properties)
    assert properties["resource_uids"]["maxItems"] == 20
    assert properties["resource_uids"]["items"]["pattern"] == r"^[A-Za-z0-9]{11}$"
    assert "expected_revision" in write["input_schema"]["required"]
    assert tool_annotations("get_card_app_resources").read_only_hint is True
    assert tool_annotations("set_card_app_resource_selection").read_only_hint is False


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_mcp_native_selection_cleanup_and_private_denial(board, monkeypatch):
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    EmployeeMembershipPolicy.__table__.create(DbEngine.get_main_engine())
    connection, _, binding, resources, card = prepare(board)
    args = board[2].get_uid(), card.get_uid(), connection.get_uid()
    injected = {"user": board[1], "service": DomainService()}
    assert get_card_app_resources(*args, **injected)["revision"] is None
    first = set_card_app_resource_selection(*args, [resources[0].get_uid()], None, **injected)
    assert first["revision"] == 1 and first["changed"] is True
    assert get_card_app_resources(*args, **injected)["resource_uids"] == [resources[0].get_uid()]
    with pytest.raises(ToolError, match="selection changed"):
        set_card_app_resource_selection(*args, [], None, **injected)
    with DbSession.atomic() as db:
        binding.granted_capabilities = []
        db.update(binding)
    with pytest.raises(ToolError, match="configuration unavailable"):
        set_card_app_resource_selection(*args, [resources[1].get_uid()], 1, **injected)
    assert set_card_app_resource_selection(*args, [], 1, **injected)["revision"] == 2
    with DbSession.atomic() as db:
        card.visibility = "PRIVATE"
        card.owner_user_id = board[1].id
        card.created_by_user_id = board[1].id
        db.update(card)
    # Native policy allows the private owner on MCP, never another administrator.
    assert get_card_app_resources(*args, **injected)["revision"] == 2
    with DbSession.atomic() as db:
        card.owner_user_id = 2
        card.created_by_user_id = 2
        db.update(card)
    with pytest.raises(ToolError, match="configuration unavailable"):
        get_card_app_resources(*args, **injected)
    with pytest.raises(ToolError, match="configuration unavailable"):
        set_card_app_resource_selection(*args, [], 2, **injected)


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
async def test_fastmcp_native_catalog_configuration_and_group_revocation(board, monkeypatch):
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    EmployeeMembershipPolicy.__table__.create(DbEngine.get_main_engine())
    connection, _, _, resources, card = prepare(board)
    server = _create_fastmcp()
    server.add_provider(create_native_domain_provider(McpServer._wrap_tool, modern_annotations=True))
    names = ["get_card_app_resources", "set_card_app_resource_selection"]
    group = McpToolGroup(name="Card resources acceptance", tools=names, activated_at=SafeDateTime.now())
    token = mcp_auth_context.set({"user_or_bot": board[1], "tool_group": group})
    scope = {"project_uid": board[2].get_uid(), "card_uid": card.get_uid(), "connection_uid": connection.get_uid()}
    try:
        async with Client(server) as client:
            assert {tool.name for tool in await client.list_tools()} == set(names)
            empty = await client.call_tool(names[0], scope)
            assert empty.structured_content["revision"] is None
            saved = await client.call_tool(
                names[1], {**scope, "resource_uids": [resources[0].get_uid()], "expected_revision": None}
            )
            assert saved.structured_content["revision"] == 1
            with pytest.raises(ToolError, match="selection changed"):
                await client.call_tool(names[1], {**scope, "resource_uids": [], "expected_revision": None})
            group.tools = []
            assert await client.list_tools() == []
            with pytest.raises(ToolError):
                await client.call_tool(names[0], scope)
    finally:
        mcp_auth_context.reset(token)
