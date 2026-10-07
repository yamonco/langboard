from unittest.mock import Mock
import pytest
import tiktoken
from langchain_core.documents import Document
from langboard_shared.tasks.docling.DocumentRetrievalSettings import DocumentRetrievalSettings
from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings
from langboard_shared.tasks.docling.DocumentSqliteStore import open_sqlite_vector_store
from langboard_shared.tasks.docling.DocumentSqliteVectorStore_test import Fixture
from langboard_shared.tasks.docling.DocumentVectorQuery import search_vector_generation
from langboard_shared.tasks.docling.DocumentVectorStore import stage_vector_generation


def test_sqlite_query_returns_only_active_generation_and_enforces_token_budget(tmp_path):
    settings = DocumentRetrievalSettings(dimensions=3)
    with open_sqlite_vector_store(tmp_path / "vectors.sqlite", Fixture(), dimensions=3) as store:
        source = dict(
            board_uid="board",
            card_uid="card",
            attachment_uid="attachment",
            content_hash="hash",
            embedding_fingerprint="a" * 64,
        )
        old = stage_vector_generation(
            store, source=source, text="alpha old", splitter=DocumentSplitterSettings(), storage={"type": "sqlite"}
        )
        pointer = stage_vector_generation(
            store,
            source=source,
            text="alpha 한글 日本語 中文 " * 100,
            splitter=DocumentSplitterSettings(),
            storage={"type": "sqlite"},
        )
        hits = search_vector_generation(store, pointer, "alpha", settings, max_tokens=128)
        assert hits and all(hit["chunk_id"] in pointer["chunk_ids"] for hit in hits)
        assert not any(hit["chunk_id"] in old["chunk_ids"] for hit in hits)
        assert sum(len(tiktoken.get_encoding("cl100k_base").encode(hit["content"])) for hit in hits) <= 128


def test_backend_source_or_identifier_mismatch_is_never_returned():
    source = dict(
        board_uid="board",
        card_uid="card",
        attachment_uid="attachment",
        content_hash="hash",
        embedding_fingerprint="a" * 64,
        generation="active",
    )
    pointer = {**source, "chunk_ids": ["chunk"], "storage": {"type": "qdrant"}}
    store = Mock()
    store.similarity_search_with_score.return_value = [
        (Document(id="chunk", page_content="foreign secret", metadata={**source, "board_uid": "other"}), 1.0),
        (Document(id="foreign", page_content="old secret", metadata=source), 1.0),
    ]
    assert (
        search_vector_generation(
            store, pointer, "alpha", DocumentRetrievalSettings(store="qdrant", external_url="https://fixture.invalid")
        )
        == []
    )


def test_mmr_and_score_threshold_are_not_silently_combined():
    pointer = dict(
        board_uid="b",
        card_uid="c",
        attachment_uid="a",
        content_hash="h",
        embedding_fingerprint="a" * 64,
        generation="g",
        chunk_ids=["chunk"],
        storage={"type": "qdrant"},
    )
    settings = DocumentRetrievalSettings(
        store="qdrant", external_url="https://fixture.invalid", search_type="mmr", score_threshold=0.5
    )
    store = Mock()
    with pytest.raises(ValueError, match="not supported"):
        search_vector_generation(store, pointer, "alpha", settings)
    store.max_marginal_relevance_search.assert_not_called()


def test_official_qdrant_generation_query_accepts_real_chunk_ids_and_filters_old(tmp_path):
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient, models

    client = QdrantClient(path=str(tmp_path / "qdrant"))
    client.create_collection("fixture", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
    store = QdrantVectorStore(client, "fixture", embedding=Fixture())
    source = dict(
        board_uid="board",
        card_uid="card",
        attachment_uid="attachment",
        content_hash="hash",
        embedding_fingerprint="a" * 64,
    )
    stage_vector_generation(
        store, source=source, text="alpha old", splitter=DocumentSplitterSettings(), storage={"type": "qdrant"}
    )
    pointer = stage_vector_generation(
        store, source=source, text="alpha current", splitter=DocumentSplitterSettings(), storage={"type": "qdrant"}
    )
    settings = DocumentRetrievalSettings(store="qdrant", external_url="https://fixture.invalid", dimensions=3)
    hits = search_vector_generation(store, pointer, "alpha", settings)
    assert len(hits) == 1 and hits[0]["chunk_id"] == pointer["chunk_ids"][0]
    settings.search_type = "mmr"
    hits = search_vector_generation(store, pointer, "alpha", settings)
    assert len(hits) == 1 and hits[0]["content"] == "alpha current"
    client.close()
