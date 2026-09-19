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
