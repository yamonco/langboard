"""Legacy description → content block migration contract (Phase 3).

Server-side port of the UI contentBlockSerializer: splits serialized
editor markdown into ordered blocks using the same segmentation rules
(fenced code, $$Engine$$ spans, remaining contiguous text) so a
migrated card and an editor-saved card agree byte-for-byte on block
boundaries. Idempotent — cards that already have blocks are skipped.
"""

import re
from dataclasses import dataclass, field


ENGINE_ALIASES = {
    "mermaid": "mermaid",
    "plantuml": "plantuml",
    "graphviz": "graphviz",
    "flowchart": "flowchart",
    "Mermaid": "mermaid",
    "PlantUml": "plantuml",
    "Graphviz": "graphviz",
    "Flowchart": "flowchart",
}

FENCED_CODE_PATTERN = re.compile(r"```([\w+#.-]*)[ \t]*\n([\s\S]*?)```", re.MULTILINE)
CODE_DRAWING_PATTERN = re.compile(r"\$\$(Mermaid|PlantUml|Graphviz|Flowchart)\b([^\n]*)\n([\s\S]*?)\$\$", re.MULTILINE)


@dataclass(frozen=True)
class MigrationCandidate:
    """One card whose legacy description yields structured segments."""

    card_uid: str
    blocks: tuple[dict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MigrationReport:
    """Batch migration outcome for audit."""

    scanned: int = 0
    migrated: int = 0
    skipped_has_blocks: int = 0
    skipped_no_segments: int = 0
    failed: tuple[str, ...] = field(default_factory=tuple)


def normalize_engine(token: str | None) -> str | None:
    """Map a serialized drawing token onto the engine allowlist."""

    if not token:
        return None
    return ENGINE_ALIASES.get(token.strip())


def _meta_view_mode(meta: str | None) -> str:
    if not meta:
        return "both"
    if re.search(r'mode=["\']?code', meta, re.IGNORECASE):
        return "code"
    if re.search(r'mode=["\']?(image|rendered)', meta, re.IGNORECASE):
        return "image"
    return "both"


def extract_legacy_blocks(markdown: str) -> list[dict]:
    """Split serialized editor markdown into ordered block payloads.

    Mirrors contentBlockSerializer.extractContentBlocks in the UI: code
    fences win over $$ spans inside them, segments without code or
    diagram yield an empty list (nothing to migrate).
    """

    segments: list[tuple[int, int, dict]] = []

    for match in FENCED_CODE_PATTERN.finditer(markdown):
        language = (match.group(1) or "text").strip() or "text"
        segments.append(
            (
                match.start(),
                match.end(),
                {"block_type": "code", "payload": {"language": language, "source": match.group(2) or ""}},
            )
        )

    for match in CODE_DRAWING_PATTERN.finditer(markdown):
        engine = normalize_engine(match.group(1))
        if not engine:
            continue
        segments.append(
            (
                match.start(),
                match.end(),
                {
                    "block_type": "diagram",
                    "payload": {
                        "engine": engine,
                        "source": match.group(3) or "",
                        "view_mode": _meta_view_mode(match.group(2)),
                    },
                },
            )
        )

    if not segments:
        return []

    segments.sort(key=lambda segment: segment[0])

    blocks: list[dict] = []
    cursor = 0
    for start, end, block in segments:
        if start < cursor:
            continue
        text = re.sub(r"\n{3,}", "\n\n", markdown[cursor:start]).strip()
        if text:
            blocks.append({"block_type": "rich_text", "payload": {"text": text}})
        blocks.append(block)
        cursor = end

    tail = markdown[cursor:].strip()
    if tail:
        blocks.append({"block_type": "rich_text", "payload": {"text": tail}})
    return blocks
