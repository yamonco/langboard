import ast
from pathlib import Path


def test_column_order_tool_reuses_native_service() -> None:
    """Column reorder is an MCP tool backed by the existing service method."""

    source = (Path(__file__).parents[2] / "langboard" / "mcp_tools" / "ProjectMcp.py").read_text()
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "change_column_order"
    )

    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "change_order"
        for node in ast.walk(function)
    )
