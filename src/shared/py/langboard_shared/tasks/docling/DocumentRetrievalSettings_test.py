import math
import sqlite3
from pathlib import Path
import pytest
from langchain_core.embeddings import Embeddings
from pydantic import ValidationError
from langboard_shared.tasks.docling.DocumentRetrievalSettings import DocumentRetrievalSettings
from langboard_shared.tasks.docling.DocumentSqliteStore import open_document_store


class FixtureEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float("alpha" in text), float("beta" in text), 0.1]


def test_settings_reject_unsupported_modes_endpoints_and_unbounded_requests():
    assert DocumentRetrievalSettings().enabled is False
    for values in [
        {"store": "sqlite", "search_type": "mmr"},
        {"store": "sqlite", "external_url": "https://example.com"},
        {"store": "qdrant"},
        {"store": "qdrant", "external_url": "https://user:secret@example.com"},
        {"store": "qdrant", "external_url": "https://example.com?key=secret"},
        {"store": "qdrant", "external_url": "https://example.com", "search_type": "mmr", "k": 25, "fetch_k": 20},
        {"dimensions": True},
        {"dimensions": 65537},
        {"k": 26},
        {"max_return_tokens": 16001},
        {"timeout_seconds": math.inf},
        {"score_threshold": math.nan},
        {"lambda_mult": math.inf},
        {"splitter": {"chunk_size": 64, "chunk_overlap": 64}},
        {"custom_code": "pass"},
    ]:
        with pytest.raises(ValidationError):
            DocumentRetrievalSettings.model_validate(values)
    configured = DocumentRetrievalSettings.model_validate(
        {
            "store": "qdrant",
            "external_url": "https://example.com",
            "external_api_key": "fixture-secret",
            "search_type": "mmr",
            "k": 5,
            "fetch_k": 10,
        }
    )
    assert "fixture-secret" not in configured.model_dump_json()
    assert "fixture-secret" not in repr(configured)


def test_native_store_prefilters_persists_and_cascades_deleted_vectors(tmp_path: Path):
    path = tmp_path / "retrieval.sqlite"
    embed = FixtureEmbeddings()
    with open_document_store(path, embed, dimensions=3) as store:
        store.put(("board", "A"), "visible", {"text": "alpha 문서", "card": "allowed"})
        store.put(("board", "a"), "other-board", {"text": "alpha 秘密", "card": "allowed"})
        store.put(("board", "A"), "hidden", {"text": "alpha 隐私", "card": "denied"})
        assert [hit.key for hit in store.search(("board", "A"), query="alpha", filter={"card": "allowed"})] == [
            "visible"
        ]
        for _ in range(10):
            store.put(("board", "A"), "visible", {"text": "beta 更新", "card": "allowed"})
        assert store.conn.execute("SELECT COUNT(*) FROM store_vectors WHERE key='visible'").fetchone()[0] == 1
        store.delete(("board", "A"), "visible")
        assert store.conn.execute("SELECT COUNT(*) FROM store_vectors WHERE key='visible'").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        store.conn.execute("SELECT 1")
    with open_document_store(path, embed, dimensions=3) as reopened:
        assert [hit.key for hit in reopened.search(("board", "A"), query="alpha")] == ["hidden"]
        assert reopened.get(("board", "a"), "other-board") is not None
