import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_integration import McpTool  # noqa: E402
from langboard.mcp_tools import CapabilityMcp  # noqa: E402


class FakeUser:
    pass


class FakeService:
    pass


def test_diagnostic_schema_keeps_scope_optional() -> None:
    metadata = McpTool.get_tool("diagnose_connection")

    assert metadata is not None
    assert metadata["accessible_type"] == "user"
    assert metadata["input_schema"].get("required", []) == []
    assert "project_uid" in metadata["input_schema"]["properties"]
    assert "card_uid" in metadata["input_schema"]["properties"]


def test_diagnose_connection_reports_unknown_project_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def allowed_tool() -> dict:
        return {}

    monkeypatch.setattr(
        McpTool,
        "get_tools",
        lambda: {
            "allowed_tool": {
                "handler": allowed_tool,
                "accessible_type": "user",
                "input_schema": {"required": [], "properties": {}},
            },
            "project_tool": {
                "handler": lambda project_uid: {},
                "accessible_type": "user",
                "input_schema": {"required": ["project_uid"], "properties": {}},
            },
        },
    )

    token = CapabilityMcp.mcp_auth_context.set(
        {"tool_group": SimpleNamespace(activated_at=True, tools=["allowed_tool", "project_tool"])}
    )
    try:
        result = CapabilityMcp.diagnose_connection(FakeUser())
    finally:
        CapabilityMcp.mcp_auth_context.reset(token)

    assert result["authenticated"] is True
    assert result["scope"] == {"project_uid_present": False, "card_uid_present": False}
    assert [tool["name"] for tool in result["tools"]] == ["allowed_tool", "project_tool"]
    assert result["tools"][0]["permission"] == "allowed"
    assert result["tools"][1]["permission"] == "unknown_project_scope"


def test_scoped_permission_check_separates_allowed_and_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(CapabilityMcp.McpRoleFilter, "exists", lambda method: True)

    class FakeChecker:
        def __init__(self, service: object) -> None:
            assert service is not None

        def check_permission(self, method: object, actor: object, arguments: dict[str, Any]) -> bool:
            return arguments["project_uid"] == "readable"

    monkeypatch.setattr(CapabilityMcp, "McpRoleChecker", FakeChecker)

    assert CapabilityMcp._permission_state(FakeUser(), handler, {"project_uid": "readable"}) == "allowed"
    assert CapabilityMcp._permission_state(FakeUser(), handler, {"project_uid": "hidden"}) == "denied"


@pytest.mark.parametrize("transport", ["oauth", "legacy"])
def test_native_oauth_diagnosis_requires_no_group_and_legacy_grants_stay_bounded(monkeypatch, transport):
    checked = []

    def metadata(required, accessible="all"):
        return {"handler": object(), "accessible_type": accessible, "input_schema": {"required": required}}

    monkeypatch.setattr(
        McpTool,
        "get_tools",
        lambda: {
            "card_tool": metadata(["project_uid", "card_uid"]),
            "hidden_tool": metadata([]),
            "bot_tool": metadata([], "bot"),
        },
    )
    monkeypatch.setattr(
        CapabilityMcp, "_permission_state", lambda actor, handler, arguments: checked.append(arguments) or "denied"
    )
    auth = {"transport": transport}
    if transport == "legacy":
        auth["tool_group"] = SimpleNamespace(activated_at=True, tools=["card_tool"])
    token = CapabilityMcp.mcp_auth_context.set(auth)
    try:
        result = CapabilityMcp.diagnose_connection(FakeUser(), project_uid="project")
        tools = {tool["name"]: tool for tool in result["tools"]}
        assert tools["card_tool"]["permission"] == "unknown_card_scope"
        assert set(tools) == ({"card_tool", "hidden_tool"} if transport == "oauth" else {"card_tool"})
        assert result["tool_group"]["active"] is (transport != "oauth")
        result = CapabilityMcp.diagnose_connection(FakeUser(), project_uid="project", card_uid="card")
        assert result["tools"][0]["permission"] == "denied"
        assert checked[-1] == {"project_uid": "project", "card_uid": "card"}
    finally:
        CapabilityMcp.mcp_auth_context.reset(token)


@pytest.mark.parametrize(
    "auth", [None, {}, {"transport": "legacy"}, {"tool_group": SimpleNamespace(activated_at=None, tools=[])}]
)
def test_legacy_diagnosis_does_not_bypass_missing_or_inactive_group(auth):
    token = CapabilityMcp.mcp_auth_context.set(auth)
    try:
        with pytest.raises(ValueError, match="active MCP tool group"):
            CapabilityMcp.diagnose_connection(FakeUser())
    finally:
        CapabilityMcp.mcp_auth_context.reset(token)


def test_native_facade_diagnosis_reports_actual_command_roles(monkeypatch):
    from langboard.mcp_tools.CardMcp import delete_card

    actual = McpTool.get_tools()
    monkeypatch.setattr(McpTool, "get_tools", lambda: actual)
    monkeypatch.setattr(
        CapabilityMcp,
        "_permission_state",
        lambda actor, handler, arguments: "denied" if handler is delete_card else "allowed",
    )
    token = CapabilityMcp.mcp_auth_context.set({"transport": "oauth"})
    try:
        result = CapabilityMcp.diagnose_connection(FakeUser(), project_uid="project", card_uid="card")
        card = next(tool for tool in result["tools"] if tool["name"] == "update_card")
        assert card["permission"] == "action_dependent"
        assert card["actions"]["delete"] == "denied"
        assert card["actions"]["title"] == "allowed"
        checklist = next(tool for tool in result["tools"] if tool["name"] == "change_card_checklist")
        assert len(checklist["actions"]) == 8
    finally:
        CapabilityMcp.mcp_auth_context.reset(token)
