import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard_shared.domain.contracts.content_blocks import (  # noqa: E402
    ContentBlockConflictError,
    ContentBlockType,
    DiagramEngine,
    build_payload,
    check_revision,
    validate_language,
    validate_source,
)


class TestValidation:
    def test_language_charset(self):
        assert validate_language("python3.12") == "python3.12"
        with pytest.raises(ValueError):
            validate_language("py;thon")
        with pytest.raises(ValueError):
            validate_language("")

    def test_source_limit(self):
        with pytest.raises(ValueError):
            validate_source("x" * 65_537)

    def test_engine_allowlist(self):
        with pytest.raises(ValueError):
            build_payload(ContentBlockType.DIAGRAM, {"engine": "d3", "source": "a"})
        ok = build_payload(ContentBlockType.DIAGRAM, {"engine": "mermaid", "source": "graph TD; A-->B"})
        assert ok["engine"] == DiagramEngine.MERMAID.value

    def test_view_mode_allowlist(self):
        with pytest.raises(ValueError):
            build_payload(ContentBlockType.DIAGRAM, {"engine": "mermaid", "source": "a", "view_mode": "3d"})

    def test_code_payload_roundtrip(self):
        payload = build_payload(ContentBlockType.CODE, {"language": "python", "source": "print(1)", "title": "run"})
        assert payload == {"language": "python", "source": "print(1)", "title": "run"}

    def test_rich_text_is_literal(self):
        payload = build_payload(ContentBlockType.RICH_TEXT, {"text": "<a> 안전한 텍스트"})
        assert payload["text"] == "<a> 안전한 텍스트"


class TestRevision:
    def test_conflict_on_mismatch(self):
        with pytest.raises(ContentBlockConflictError):
            check_revision(expected_revision=1, current_revision=3)

    def test_match_passes(self):
        check_revision(expected_revision=3, current_revision=3)
