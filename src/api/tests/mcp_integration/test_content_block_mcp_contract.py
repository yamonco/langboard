import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard.card_workspace.application.commands import (  # noqa: E402
    create_card_content_block,
    move_card_content_block,
)
from langboard.mcp_integration import McpTool  # noqa: E402
from langboard.mcp_tools import CardMcp  # noqa: E402, F401
from langboard_shared.domain.contracts.content_blocks import (  # noqa: E402
    ContentBlockConflictError,
    ContentBlockType,
    DiagramEngine,
    build_payload,
    check_revision,
)


class TestToolSchema:
    def test_create_schema_requires_identity_and_type(self) -> None:
        schema = McpTool.get_tool("create_card_content_block")["input_schema"]
        assert "project_uid" in schema["required"]
        assert "card_uid" in schema["required"]
        assert "block_type" in schema["required"]
        assert "payload" in schema["required"]

    def test_update_schema_requires_revision(self) -> None:
        schema = McpTool.get_tool("update_card_content_block")["input_schema"]
        assert "expected_revision" in schema["required"]
        assert "block_uid" in schema["required"]

    def test_move_schema_rejects_double_hint_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            move_card_content_block(_Port(), "p", "c", "b", after_block_uid="x", order=0)

    def test_create_schema_rejects_unknown_type_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            create_card_content_block(_Port(), "p", "c", "iframe", {})


class _Port:
    def create_card_content_block(self, *args, **kwargs):
        return {}

    def move_card_content_block(self, *args, **kwargs):
        return None


class TestPayloadContract:
    def test_diagram_engine_allowlist(self) -> None:
        with pytest.raises(ValueError):
            build_payload(ContentBlockType.DIAGRAM, {"engine": "d3", "source": "x"})
        ok = build_payload(ContentBlockType.DIAGRAM, {"engine": "mermaid", "source": "graph TD; A-->B"})
        assert ok["engine"] == DiagramEngine.MERMAID.value

    def test_code_language_charset(self) -> None:
        with pytest.raises(ValueError):
            build_payload(ContentBlockType.CODE, {"language": "py;rm -rf", "source": "x"})

    def test_revision_conflict(self) -> None:
        with pytest.raises(ContentBlockConflictError):
            check_revision(1, 3)
