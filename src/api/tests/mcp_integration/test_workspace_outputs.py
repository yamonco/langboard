"""Workspace outputs must retain partial updates and integration receipts."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.application.commands import reconcile_card_checklist_projection, set_card_relationships
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_integration.WorkOutputs import WORK_OUTPUTS
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context


@pytest.mark.parametrize("operation", ["members", "labels", "relationships", "reconcile"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_workspace_contracts_preserve_domain_receipts_and_partial_updates(monkeypatch, operation, malformed):
    writes = []
    if operation == "members":
        name, profile = "add_project_people", "agent"
        payload = {"requested_count": 2, "changed_count": 0, "status": "unchanged"}
    elif operation == "labels":
        name, profile = "set_card_people_and_labels", "raw"
        payload = {"labels": []}
    elif operation == "relationships":
        name, profile = "set_card_relationships", "raw"
        port = SimpleNamespace(
            replace_card_relationships=lambda *args: [{"uid": "rel", "parent_name": "x" * 1001, "private": "omit"}]
        )
        payload = set_card_relationships(port, "project", "card", True, [("related", "type")])
    else:
        name, profile = "reconcile_card_checklist_projection", "raw"
        port = SimpleNamespace(
            reconcile_card_checklist_projection=lambda *args: {
                "changed": False,
                "receipt": "a" * 64,
                "checklist": {"uid": "list", "title": "Tasks", "checkitems": []},
            }
        )
        payload = reconcile_card_checklist_projection(port, "project", "card", "integration.tasks", "Tasks", [], None)

    if malformed:
        payload = {**payload, "private": "must not leak"}

    def handler(value: int) -> dict:
        writes.append(value)
        return payload

    metadata = {"handler": handler, "description": "Workspace", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda tool_name: metadata if tool_name == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app(profile)
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            if profile == "raw":
                result = await client.call_tool("search_raw_tools", {"pattern": "^" + name + r"\b"})
                schema = json.loads(result.content[0].text)[0]["outputSchema"]
            else:
                schema = (await client.list_tools())[0].output_schema
            assert schema["additionalProperties"] is False
            result = await client.call_tool(
                "call_raw_tool" if profile == "raw" else name,
                {"name": name, "arguments": {"value": 1}} if profile == "raw" else {"value": 1},
                raise_on_error=False,
            )
            assert writes == [1]
            if malformed:
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert "must not leak" not in str(result.content)
            else:
                assert not result.is_error
                assert result.structured_content == payload
                assert result.meta["mutation_receipt"]["outcome"] == "applied"
                if operation == "labels":
                    assert "member_uids" not in result.structured_content
                if operation == "reconcile":
                    assert result.structured_content["receipt"] == "a" * 64
                    assert result.structured_content["changed"] is False
    finally:
        mcp_auth_context.reset(token)


def test_invitation_output_keeps_counts_without_recipient_data():
    payload = {"requested_count": 2, "changed_count": 1, "status": "updated"}
    assert WORK_OUTPUTS["invite_project_members"].model_validate(payload).model_dump() == payload
