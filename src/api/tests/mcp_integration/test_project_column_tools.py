import ast
import os
from pathlib import Path
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools.ProjectMcp import _column_target_order  # noqa: E402


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


def test_relative_column_order_rejects_foreign_anchor_and_conflicting_selectors() -> None:
    columns = [{"uid": "todo"}, {"uid": "doing"}, {"uid": "done"}]
    assert _column_target_order(columns, position="leftmost", after_column_uid=None, before_column_uid=None) == 0
    assert _column_target_order(columns, position=None, after_column_uid="doing", before_column_uid=None) == 2
    assert (
        _column_target_order(columns, position=None, after_column_uid=None, before_column_uid="done", moving_uid="todo")
        == 1
    )
    with pytest.raises(ValueError, match="not found"):
        _column_target_order(columns, position=None, after_column_uid="other-board", before_column_uid=None)
    with pytest.raises(ValueError, match="Choose one"):
        _column_target_order(columns, position="leftmost", after_column_uid="doing", before_column_uid=None)
