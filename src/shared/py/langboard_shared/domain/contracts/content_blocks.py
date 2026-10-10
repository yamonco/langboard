"""Structured content block contracts for cards.

Code and diagram (Mermaid etc.) live as first-class typed blocks instead
of Markdown syntax assembled inside the description string. Pure
validation and payload rules; persistence lives in the model layer.
"""

from dataclasses import dataclass
from enum import Enum


class ContentBlockType(str, Enum):
    """Kinds of structured content a card can hold."""

    RICH_TEXT = "rich_text"
    CODE = "code"
    DIAGRAM = "diagram"


class DiagramEngine(str, Enum):
    """Allowed diagram renderers (never an arbitrary string)."""

    MERMAID = "mermaid"
    PLANTUML = "plantuml"
    GRAPHVIZ = "graphviz"
    FLOWCHART = "flowchart"


class DiagramViewMode(str, Enum):
    """How a diagram is presented in the card viewer."""

    SOURCE = "source"
    RENDERED = "rendered"
    BOTH = "both"


MAX_SOURCE_CHARS = 65_536
MAX_LANGUAGE_CHARS = 48
LANGUAGE_PATTERN_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-_#.")


class ContentBlockConflictError(ValueError):
    """Raised when an update carries a stale block revision."""


def validate_language(language: str) -> str:
    """Accept a safe language identifier or raise."""

    if not language or len(language) > MAX_LANGUAGE_CHARS:
        raise ValueError(f"language must be 1..{MAX_LANGUAGE_CHARS} chars")
    if not set(language) <= LANGUAGE_PATTERN_OK:
        raise ValueError("language may only contain letters, digits, + - _ # .")
    return language


def validate_source(source: str) -> str:
    """Enforce the literal source size limit."""

    if not isinstance(source, str):
        raise ValueError("source must be a literal string")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"source exceeds {MAX_SOURCE_CHARS} chars")
    return source


@dataclass(frozen=True)
class CodePayload:
    """Literal code attached to a card."""

    language: str
    source: str
    title: str | None = None

    def __post_init__(self) -> None:
        validate_language(self.language)
        validate_source(self.source)
        if self.title is not None and len(self.title) > 200:
            raise ValueError("title too long")

    def to_payload(self) -> dict[str, object]:
        return {"language": self.language, "source": self.source, "title": self.title}


@dataclass(frozen=True)
class DiagramPayload:
    """Literal diagram source with a fixed engine."""

    engine: DiagramEngine
    source: str
    view_mode: DiagramViewMode = DiagramViewMode.BOTH

    def __post_init__(self) -> None:
        if not isinstance(self.engine, DiagramEngine):
            raise ValueError(f"engine must be one of {[e.value for e in DiagramEngine]}")
        validate_source(self.source)
        if not isinstance(self.view_mode, DiagramViewMode):
            raise ValueError(f"view_mode must be one of {[v.value for v in DiagramViewMode]}")

    def to_payload(self) -> dict[str, object]:
        return {"engine": self.engine.value, "source": self.source, "view_mode": self.view_mode.value}


def build_payload(block_type: ContentBlockType, payload: dict[str, object]) -> dict[str, object]:
    """Validate and normalize a write payload for one block type."""

    if block_type is ContentBlockType.CODE:
        return CodePayload(
            language=str(payload.get("language", "")),
            source=str(payload.get("source", "")),
            title=payload.get("title"),
        ).to_payload()
    if block_type is ContentBlockType.DIAGRAM:
        try:
            engine = DiagramEngine(str(payload.get("engine", "")))
        except ValueError as exc:
            raise ValueError(f"unknown diagram engine '{payload.get('engine')}'") from exc
        try:
            view_mode = DiagramViewMode(str(payload.get("view_mode", DiagramViewMode.BOTH.value)))
        except ValueError as exc:
            raise ValueError(f"unknown view_mode '{payload.get('view_mode')}'") from exc
        return DiagramPayload(
            engine=engine,
            source=str(payload.get("source", "")),
            view_mode=view_mode,
        ).to_payload()
    # rich_text keeps a plain literal text payload for now
    text = str(payload.get("text", ""))
    validate_source(text)
    return {"text": text}


def check_revision(expected_revision: int, current_revision: int) -> None:
    """Reject stale writes with a dedicated conflict error."""

    if expected_revision != current_revision:
        raise ContentBlockConflictError(
            f"block revision mismatch: expected {current_revision}, got {expected_revision}"
        )


def merge_order_hint(order: int | None, after_block_uid: str | None, sibling_count: int) -> int:
    """Resolve a create position from an explicit order or an after-anchor.

    Returns the insertion index; callers splice and renumber.
    """

    if after_block_uid is not None:
        if order is not None:
            raise ValueError("pass either order or after_block_uid, not both")
        # The caller resolves the anchor uid to its index; here we only
        # reject the impossible case of an empty board.
        if sibling_count < 0:
            raise ValueError("invalid sibling count")
        return -1
    if order is None:
        return sibling_count
    if order < 0 or order > sibling_count:
        raise ValueError(f"order must be 0..{sibling_count}")
    return order
