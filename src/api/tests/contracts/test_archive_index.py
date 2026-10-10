import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.archive_index import (  # noqa: E402
    MemoryDoc,
    build_index,
    recall,
    related_entities,
    search,
    tokenize,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 13, 0, 0, tzinfo=UTC)


def doc(uid: str, text: str, entities=(), minutes: float = 0.0) -> MemoryDoc:
    return MemoryDoc(
        source_uid=uid,
        kind="card",
        text=text,
        entities=tuple(entities),
        occurred_at=BASE + timedelta(minutes=minutes),
    )


class TestMemoryDoc:
    def test_rejects_blank_text(self):
        with pytest.raises(ValueError):
            doc("d1", "   ")

    def test_rejects_duplicate_entities(self):
        with pytest.raises(ValueError):
            doc("d1", "text", entities=("a", "a"))


class TestTokenize:
    def test_lowercases_and_strips_punctuation(self):
        assert tokenize("Hello, Langboard-world!") == ("hello", "langboard", "world")


class TestBuildIndex:
    def test_rejects_duplicate_sources(self):
        with pytest.raises(ValueError):
            build_index([doc("d1", "a"), doc("d1", "b")])

    def test_pairs_counted_once_per_doc(self):
        index = build_index([doc("d1", "text", entities=("user-a", "user-b"))])
        assert index.pair_counts == {frozenset(("user-a", "user-b")): 1}


class TestSearch:
    def test_ranks_by_term_matches_then_recency(self):
        index = build_index(
            [
                doc("old", "deploy pipeline failed", minutes=0),
                doc("new", "deploy pipeline fixed today", minutes=10),
                doc("other", "unrelated content", minutes=20),
            ]
        )
        assert search(index, "deploy pipeline") == ("new", "old")

    def test_empty_query_returns_nothing(self):
        index = build_index([doc("d1", "content")])
        assert search(index, "  ") == ()

    def test_limit_respected(self):
        index = build_index([doc(f"d{i}", "shared term", minutes=i) for i in range(5)])
        assert len(search(index, "shared", limit=2)) == 2


class TestRelatedEntities:
    def test_strength_ordering(self):
        index = build_index(
            [
                doc("d1", "text", entities=("core", "alice")),
                doc("d2", "text", entities=("core", "bob")),
                doc("d3", "text", entities=("core", "bob")),
            ]
        )
        assert related_entities(index, "core") == (("bob", 2), ("alice", 1))

    def test_unknown_entity_empty(self):
        index = build_index([doc("d1", "text", entities=("a",))])
        assert related_entities(index, "ghost") == ()


class TestRecall:
    def test_most_recent_first(self):
        index = build_index(
            [
                doc("older", "text", entities=("alice",), minutes=0),
                doc("newer", "text", entities=("alice",), minutes=30),
            ]
        )
        assert recall(index, "alice") == ("newer", "older")
