"""Plan tools bind the role-filtered project before entering the transaction owner."""

from unittest.mock import Mock
import pytest
from langboard.card_workspace.application.work_plan import WorkPlan
from langboard.mcp_integration import McpRoleFilter, McpTool
from langboard.mcp_integration.Annotations import tool_annotations
from langboard.mcp_integration.Providers import AGENT_CORE_TOOLS
from langboard.mcp_tools import CardMcp


@pytest.mark.parametrize("apply", [False, True])
def test_plan_mcp_project_binding_and_native_owner(monkeypatch, apply):
    plan = WorkPlan(
        project_uid="board",
        anchor_card_uid="anchor",
        new_checklists=[{"target_card_ref": "anchor", "title": "Steps", "items": ["Verify"]}],
    )
    owner = Mock()
    constructor = Mock(return_value=owner)
    monkeypatch.setattr(CardMcp, "WorkPlanService", constructor)
    actor, service = object(), object()
    handler = CardMcp.apply_card_work_plan if apply else CardMcp.preview_card_work_plan
    args = (plan, "a" * 64, "request") if apply else (plan,)
    with pytest.raises(ValueError, match="authorized project"):
        handler("other-board", *args, actor, service)
    constructor.assert_not_called()
    result = handler("board", *args, actor, service)
    constructor.assert_called_once_with(actor, service)
    method = owner.apply if apply else owner.preview
    method.assert_called_once_with(*args)
    assert result is method.return_value
    actions = McpRoleFilter.get_filtered(handler)[1]
    assert actions == (["read", "card_update"] if apply else ["read"])
    name = handler.__name__
    assert name in AGENT_CORE_TOOLS
    schema = McpTool.get_tool(name)["input_schema"]
    assert "user_or_bot" not in schema["properties"] and "service" not in schema["properties"]
    assert {"project_uid", "plan"} <= set(schema["required"])
    assert tool_annotations(name).read_only_hint is (not apply)
