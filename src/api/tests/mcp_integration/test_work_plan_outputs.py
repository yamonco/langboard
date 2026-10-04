"""Native plan records and persisted JSON replay preserve the same typed contract."""

import json
from types import SimpleNamespace
import pytest
from fastmcp import Client
from langboard.card_workspace.application.work_plan import WorkPlan
from langboard.mcp_integration.Server import McpServer
from langboard.mcp_integration.Tool import McpTool
from langboard.mcp_integration.WorkPlanOutputs import WorkPlanApplyOutput, WorkPlanPreviewOutput
from langboard.middlewares.McpAuthMiddleware import mcp_auth_context
from langboard_shared.domain.models import Card, Checkitem, Checklist
from pydantic import TypeAdapter, ValidationError


def native_result():
    card = Card(id=123, project_id=456, project_column_id=789, title="Promoted")
    checklist = Checklist(id=222, card_id=123, title="Steps")
    item = Checkitem(id=333, checklist_id=222, title="Verify")
    return {
        "graph": None,
        "cardifications": [{"card": card.api_response(), "source_checkitem_uid": "source"}],
        "checklists": [
            {
                "target_card_uid": card.get_uid(),
                "checklist": checklist.api_response(),
                "checkitems": [item.api_response()],
            }
        ],
        "applied_revision": "a" * 64,
        "all_succeeded": True,
        "replayed": False,
    }


def test_native_and_persisted_replay_contract():
    native = native_result()
    initial = WorkPlanApplyOutput.model_validate(native).model_dump(mode="json")
    replay = json.loads(json.dumps(TypeAdapter(dict).dump_python(native, mode="json")))
    assert WorkPlanApplyOutput.model_validate(replay).model_dump(mode="json") == initial
    for bad in (False, 1, "true"):
        with pytest.raises(ValidationError):
            WorkPlanApplyOutput.model_validate({**native, "all_succeeded": bad})
    plan = WorkPlan(
        project_uid="board",
        anchor_card_uid="anchor",
        new_checklists=[{"target_card_ref": "anchor", "title": "Steps", "items": ["Verify"]}],
    )
    assert (
        WorkPlanPreviewOutput.model_validate(
            {
                "revision": "a" * 64,
                "plan": plan.model_dump(mode="json"),
                "counts": {"cards": 0, "cardifications": 0, "checklists": 1},
            }
        ).plan
        == plan
    )


@pytest.mark.parametrize("malformed", [False, True])
async def test_fastmcp_schema_and_unknown_post_save_receipt(monkeypatch, malformed):
    payload = native_result()
    effects = []

    def handler() -> dict:
        effects.append("saved")
        if malformed:
            payload["checklists"][0]["target_card_uid"] = 1
        return payload

    name = "apply_card_work_plan"
    metadata = {"handler": handler, "description": "Apply plan", "exclude": [], "accessible_type": "all"}
    monkeypatch.setattr(McpTool, "get_tools", lambda: {name: metadata})
    monkeypatch.setattr(McpTool, "get_tool", lambda key: metadata if key == name else None)
    monkeypatch.setattr(McpServer, "_validate_auth", lambda *args: True)
    monkeypatch.setattr(McpServer, "_validate_role", lambda *args, **kwargs: True)
    _, server = McpServer.get_http_app("agent")
    token = mcp_auth_context.set(
        {"user_or_bot": object(), "tool_group": SimpleNamespace(activated_at=object(), tools=[name])}
    )
    try:
        async with Client(server) as client:
            schema = (await client.list_tools())[0].output_schema
            assert schema["properties"]["applied_revision"]["pattern"] == "^[0-9a-f]{64}$"
            result = await client.call_tool(name, {}, raise_on_error=False)
            assert effects == ["saved"]
            if malformed:
                assert result.is_error
                assert result.meta["mutation_receipt"]["outcome"] == "unknown"
                assert result.meta["mutation_receipt"]["retryable"] is False
            else:
                assert not result.is_error
                assert result.structured_content["all_succeeded"] is True
    finally:
        mcp_auth_context.reset(token)
