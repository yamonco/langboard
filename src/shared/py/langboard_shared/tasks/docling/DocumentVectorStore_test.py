from unittest.mock import Mock
import pytest
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models
from langboard_shared.tasks.docling.DocumentRetrievalSettings import DocumentRetrievalSettings
from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings
from langboard_shared.tasks.docling.DocumentVectorStore import (
    delete_vector_generation,
    open_qdrant_store,
    stage_vector_generation,
)


class Fixture(Embeddings):
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [float("alpha" in text), float("beta" in text), 0.1]


def test_official_store_persists_sources_filters_and_deletes(tmp_path):
    client = QdrantClient(path=str(tmp_path / "vectors"))
    client.create_collection("documents", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
    store = QdrantVectorStore(client, "documents", embedding=Fixture())
    source = dict(
        board_uid="board",
        card_uid="card",
        attachment_uid="attachment",
        content_hash="hash",
        embedding_fingerprint="a" * 64,
    )
    pointer = stage_vector_generation(
        store,
        source=source,
        text="alpha 한글 日本語 中文",
        splitter=DocumentSplitterSettings(),
        storage={"type": "qdrant"},
    )
    other = stage_vector_generation(
        store,
        source={**source, "board_uid": "other"},
        text="alpha private",
        splitter=DocumentSplitterSettings(),
        storage={"type": "qdrant"},
    )
    filter = models.Filter(
        must=[models.FieldCondition(key="metadata.board_uid", match=models.MatchValue(value="board"))]
    )
    hits = store.similarity_search("alpha", k=5, filter=filter)
    assert len(hits) == 1 and hits[0].metadata["content_hash"] == "hash"
    client.close()
    client = QdrantClient(path=str(tmp_path / "vectors"))
    store = QdrantVectorStore(client, "documents", embedding=Fixture())
    assert client.retrieve("documents", ids=pointer["chunk_ids"])
    delete_vector_generation(store, pointer)
    delete_vector_generation(store, pointer)
    assert not client.retrieve("documents", ids=pointer["chunk_ids"])
    assert client.retrieve("documents", ids=other["chunk_ids"])
    client.close()


def test_partial_failure_cleans_requested_ids():
    store = Mock()
    store.add_documents.side_effect = RuntimeError("fixture failure")
    source = dict(board_uid="b", card_uid="c", attachment_uid="a", content_hash="h", embedding_fingerprint="a" * 64)
    with pytest.raises(RuntimeError):
        stage_vector_generation(
            store, source=source, text="alpha", splitter=DocumentSplitterSettings(), storage={"type": "qdrant"}
        )
    assert store.delete.call_args.kwargs["ids"] == store.add_documents.call_args.kwargs["ids"]


def test_unapproved_endpoint_never_constructs_client(monkeypatch):
    client = Mock()
    monkeypatch.setattr("qdrant_client.QdrantClient", client)
    settings = DocumentRetrievalSettings(store="qdrant", external_url="https://fixture.invalid")
    with pytest.raises(ValueError, match="approved"):
        with open_qdrant_store(settings, Fixture(), "a" * 64, set()):
            pass
    client.assert_not_called()


def test_connection_factory_validates_collection_and_supports_provider_free_cleanup(monkeypatch, tmp_path):
    client = QdrantClient(path=str(tmp_path / "factory"))
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **_: client)
    fingerprint = "a" * 64
    settings = DocumentRetrievalSettings(store="qdrant", external_url="https://fixture.invalid", dimensions=3)
    source = dict(board_uid="b", card_uid="c", attachment_uid="a", content_hash="h", embedding_fingerprint=fingerprint)
    with open_qdrant_store(settings, Fixture(), fingerprint, {"https://fixture.invalid"}) as store:
        pointer = stage_vector_generation(
            store, source=source, text="alpha", splitter=DocumentSplitterSettings(), storage={"type": "qdrant"}
        )
    client = QdrantClient(path=str(tmp_path / "factory"))
    with open_qdrant_store(settings, None, fingerprint, {"https://fixture.invalid"}, create=False) as store:
        delete_vector_generation(store, pointer)
        assert not client.retrieve("langboard_documents_" + fingerprint, ids=pointer["chunk_ids"])
    client = QdrantClient(path=str(tmp_path / "factory"))
    settings.dimensions = 4
    with pytest.raises(ValueError, match="configuration"):
        with open_qdrant_store(settings, None, fingerprint, {"https://fixture.invalid"}, create=False):
            pass
