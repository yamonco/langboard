"""MCP transport contract tests for card workspace tools."""

import pytest
from langboard.card_workspace.domain import CardBundleInclude, ChecklistProjectionItem
from langboard.mcp_tools.CardWorkspaceMcp import JsonCardBundleInclude, JsonChecklistProjectionItem
from pydantic import TypeAdapter, ValidationError


def test_card_bundle_include_accepts_json_strings_and_rejects_unknown_values() -> None:
    """Keep the advertised JSON schema aligned with runtime validation."""

    adapter = TypeAdapter(list[JsonCardBundleInclude])
    assert adapter.validate_python(["description", "metadata"], strict=True) == [
        CardBundleInclude.Description,
        CardBundleInclude.Metadata,
    ]
    with pytest.raises(ValidationError):
        adapter.validate_python(["unknown"], strict=True)


def test_checklist_projection_item_accepts_json_objects() -> None:
    """Accept the JSON object shape advertised by the MCP tool schema."""

    adapter = TypeAdapter(list[JsonChecklistProjectionItem])
    assert adapter.validate_python(
        [{"key": "invoice:2026-08", "title": "August invoice"}],
        strict=True,
    ) == [ChecklistProjectionItem("invoice:2026-08", "August invoice")]

    with pytest.raises(ValidationError):
        adapter.validate_python([{"key": "invalid key", "title": "August invoice"}], strict=True)
