"""Hindsight AI long-term memory index over archived content.

Builds an inverted term index plus entity co-occurrence graph from
archived memory documents, enabling recall searches and relationship
tracking across cold-stored history. Pure in-memory structures.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


@dataclass(frozen=True)
class MemoryDoc:
    """One archived unit of long-term memory."""

    source_uid: str
    kind: str  # "card" | "comment" | "wiki"
    text: str
    entities: tuple[str, ...] = field(default_factory=tuple)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.source_uid or not self.kind.strip():
            raise ValueError("source_uid and kind are required")
        if not self.text.strip():
            raise ValueError("text is required")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if len(set(self.entities)) != len(self.entities):
            raise ValueError("duplicate entities")


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercased word tokens without punctuation noise."""

    cleaned = "".join(char if char.isalnum() else " " for char in text.lower())
    return tuple(token for token in cleaned.split() if len(token) > 1)


@dataclass(frozen=True)
class MemoryIndex:
    """Immutable index snapshot for search and relationship recall."""

    term_docs: dict[str, frozenset[str]]
    doc_entities: dict[str, tuple[str, ...]]
    pair_counts: dict[frozenset[str], int]
    docs: dict[str, MemoryDoc]


def build_index(documents: Sequence[MemoryDoc]) -> MemoryIndex:
    """Index documents into term postings and entity co-occurrence."""

    term_docs: dict[str, set[str]] = {}
    doc_entities: dict[str, tuple[str, ...]] = {}
    pair_counts: dict[frozenset[str], int] = {}
    docs: dict[str, MemoryDoc] = {}

    for doc in documents:
        if doc.source_uid in docs:
            raise ValueError(f"duplicate source_uid {doc.source_uid}")
        docs[doc.source_uid] = doc
        doc_entities[doc.source_uid] = doc.entities
        for term in tokenize(doc.text):
            term_docs.setdefault(term, set()).add(doc.source_uid)
        ordered = sorted(doc.entities)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pair_counts[frozenset((left, right))] = pair_counts.get(frozenset((left, right)), 0) + 1

    return MemoryIndex(
        term_docs={term: frozenset(u for u in uids) for term, uids in term_docs.items()},
        doc_entities=doc_entities,
        pair_counts=pair_counts,
        docs=docs,
    )


def search(index: MemoryIndex, query: str, limit: int = 10) -> tuple[str, ...]:
    """Rank documents by matched term count with recent-first tie-breaks."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    terms = tokenize(query)
    if not terms:
        return ()
    scores: dict[str, int] = {}
    for term in terms:
        for uid in index.term_docs.get(term, ()):  # term_docs values are frozensets
            scores[uid] = scores.get(uid, 0) + 1
    ranked = sorted(
        scores,
        key=lambda uid: (-scores[uid], -(index.docs[uid].occurred_at.timestamp()), uid),
    )
    return tuple(ranked[:limit])


def related_entities(index: MemoryIndex, entity: str, limit: int = 10) -> tuple[tuple[str, int], ...]:
    """Return entities co-occurring with the given one, strongest first."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    counts: dict[str, int] = {}
    for pair, count in index.pair_counts.items():
        if entity in pair:
            other = next(member for member in pair if member != entity)
            counts[other] = counts.get(other, 0) + count
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(ranked[:limit])


def recall(index: MemoryIndex, entity: str, limit: int = 5) -> tuple[str, ...]:
    """Recall the most recent documents mentioning an entity."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    hits = [uid for uid, entities in index.doc_entities.items() if entity in entities]
    hits.sort(key=lambda uid: (-index.docs[uid].occurred_at.timestamp(), uid))
    return tuple(hits[:limit])
