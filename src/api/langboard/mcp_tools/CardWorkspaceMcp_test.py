"""MCP transport contract tests for card workspace tools."""

import pytest
from langboard.card_workspace.domain import CardBundleInclude
from langboard.mcp_tools.CardWorkspaceMcp import JsonCardBundleInclude
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
