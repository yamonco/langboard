from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
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
