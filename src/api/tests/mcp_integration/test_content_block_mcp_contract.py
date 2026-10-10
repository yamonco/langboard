import os
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
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
            CardMcp.move_card_content_block("p", "c", "b", after_block_uid="x", order=0)

    def test_create_schema_rejects_unknown_type_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            CardMcp.create_card_content_block("p", "c", "iframe", {})


def test_content_block_tools_use_native_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    block = SimpleNamespace(
        get_uid=lambda: "block", block_type="code", order=0, revision=1, payload={"source": "x"}, updated_at=None
    )
    native = SimpleNamespace(
        create=lambda *args: (calls.append("create") or block),
        update=lambda *args: (calls.append("update") or block),
        delete=lambda *args: (calls.append("delete") or True),
        move=lambda *args: (calls.append("move") or True),
    )
    service = SimpleNamespace(card_content_block=native)
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))

    assert (
        CardMcp.create_card_content_block("p", "c", "code", {"source": "x"}, service=service)["content_block"][
            "block_uid"
        ]
        == "block"
    )
    assert (
        CardMcp.update_card_content_block("p", "c", "block", 1, {"source": "y"}, service=service)["content_block"][
            "block_uid"
        ]
        == "block"
    )
    assert CardMcp.delete_card_content_block("p", "c", "block", service=service) == {"deleted": True}
    assert CardMcp.move_card_content_block("p", "c", "block", order=0, service=service) == {"moved": True}
    assert calls == ["create", "update", "delete", "move"]


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
