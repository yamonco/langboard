from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
import pytest
from pydantic import BaseModel


_SUBJECT = Path(__file__).parents[2] / "langboard" / "mcp_integration" / "Tool.py"
_SPEC = spec_from_file_location("langboard_mcp_tool_contract", _SUBJECT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
McpTool = _MODULE.McpTool


class User:
    """Test double matching the runtime-injected user type name."""


class DomainService:
    """Test double matching the runtime-injected service type name."""


class NestedFilter(BaseModel):
    """Nested business input used to verify root JSON Schema definitions."""

    query: str
    limit: int = 5


def test_optional_parameters_remain_model_visible() -> None:
    """Optional business inputs must not be confused with injected values."""

    tool_name = "schema_contract_optional_inputs"

    @McpTool.add(description="schema contract")
    def schema_contract_optional_inputs(
        card_uid: str,
        title: str | None = None,
        comments_limit: int = 5,
        include: list[str] | None = None,
        user: User | None = None,
        service: DomainService | None = None,
    ) -> dict[str, Any]:
        return {}

    try:
        metadata = McpTool.get_tool(tool_name)
        assert metadata is not None
        assert metadata["exclude"] == ["user", "service"]
        assert metadata["input_schema"]["required"] == ["card_uid"]
        properties = metadata["input_schema"]["properties"]
        assert set(properties) == {"card_uid", "title", "comments_limit", "include"}
        assert properties["comments_limit"]["type"] == "integer"
        assert properties["comments_limit"]["default"] == 5
        assert properties["include"]["anyOf"][0]["items"]["type"] == "string"
    finally:
        McpTool._tools.pop(tool_name, None)


def test_nested_models_emit_root_defs_with_resolvable_refs() -> None:
    """Nested model refs must point at root definitions accepted by MCP registries."""

    tool_name = "schema_contract_root_defs"

    @McpTool.add(description="root defs contract")
    def schema_contract_root_defs(filters: list[NestedFilter]) -> dict[str, Any]:
        return {}

    try:
        metadata = McpTool.get_tool(tool_name)
        assert metadata is not None
        schema = metadata["input_schema"]
        assert "NestedFilter" in schema["$defs"]
        assert schema["properties"]["filters"]["items"] == {"$ref": "#/$defs/NestedFilter"}
        assert "$defs" not in schema["properties"]["filters"]
    finally:
        McpTool._tools.pop(tool_name, None)


def test_registration_collision_preserves_original_handler_schema_and_access_policy():
    def original(card_uid: str, user: User) -> dict:
        return {"owner": "native"}

    def replacement(repository: str) -> dict:
        return {"owner": "replacement"}

    original.__name__ = replacement.__name__ = "collision_contract"
    try:
        McpTool.add("user", description="Native contract")(original)
        before = McpTool.get_tool("collision_contract")
        with pytest.raises(ValueError, match="MCP tool already registered: collision_contract"):
            McpTool.add("all", description="Replacement contract")(replacement)
        after = McpTool.get_tool("collision_contract")
        assert after is before
        assert after["handler"] is original
        assert after["accessible_type"] == "user"
        assert after["description"] == "Native contract"
        assert set(after["input_schema"]["properties"]) == {"card_uid"}
        assert after["exclude"] == ["user"]
        with pytest.raises(ValueError, match="already registered"):
            McpTool.add()(original)
    finally:
        McpTool._tools.pop("collision_contract", None)


def test_failed_schema_registration_does_not_reserve_tool_name():
    def invalid(*args) -> dict:
        return {}

    def valid(value: str) -> dict:
        return {"value": value}

    invalid.__name__ = valid.__name__ = "failed_schema_contract"
    try:
        with pytest.raises(Exception):
            McpTool.add()(invalid)
        assert McpTool.get_tool("failed_schema_contract") is None
        McpTool.add()(valid)
        assert McpTool.get_tool("failed_schema_contract")["handler"] is valid
    finally:
        McpTool._tools.pop("failed_schema_contract", None)


def test_native_column_scope_names_preserve_legacy_schema_and_project_policy():
    from langboard.Loader import ModuleLoader
    from langboard.mcp_integration.RoleFilter import McpRoleFilter
    from langboard.mcp_integration.Tool import McpTool as NativeTools
    from langboard_shared.domain.models.ProjectRole import ProjectRoleAction

    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    legacy = NativeTools.get_tool("get_column_bot_scopes")
    project = NativeTools.get_tool("get_project_column_bot_scopes")
    assert set(legacy["input_schema"]["required"]) == {"project_uid", "column_uid"}
    assert set(project["input_schema"]["required"]) == {"project_uid"}
    assert legacy["handler"].__module__.endswith("BotMcp")
    assert project["handler"].__module__.endswith("ProjectMcp")
    assert McpRoleFilter.get_filtered(legacy["handler"])[1] == [ProjectRoleAction.Update.value]
    assert McpRoleFilter.get_filtered(project["handler"])[1] == [ProjectRoleAction.Read.value]
