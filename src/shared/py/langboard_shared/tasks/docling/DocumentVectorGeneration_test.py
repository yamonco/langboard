from pathlib import Path
import pytest
from langchain_core.embeddings import Embeddings
from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings
from langboard_shared.tasks.docling.DocumentSqliteStore import open_document_store
from langboard_shared.tasks.docling.DocumentVectorGeneration import (
    delete_attachment_generation,
    embedding_fingerprint,
    replace_attachment_generation,
)


class FixtureEmbeddings(Embeddings):
    fail = False
    invalid = False

    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("fixture provider unavailable")
        if self.invalid:
            return [[1.0, float("nan")] for _ in texts]
        return [[1.0, 0.1, 0.1] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.1, 0.1]


def test_generation_swap_is_atomic_and_retains_previous_when_provider_fails(tmp_path: Path):
    embed = FixtureEmbeddings()
    source = dict(
        board_uid="Board",
        card_uid="card",
        attachment_uid="attachment",
        content_hash="hash",
        fingerprint=embedding_fingerprint(
            provider="https://fixture.invalid", model="embed", dimensions=3, version="v1"
        ),
        splitter=DocumentSplitterSettings(chunk_size=64, chunk_overlap=8),
        page=2,
    )
    with open_document_store(tmp_path / "generation.sqlite", embed, dimensions=3) as store:
        first = replace_attachment_generation(store, text="한글 日本語 中文 document. " * 20, **source)
        assert store.get(("document_active", "Board"), "attachment").value == first
        hits = store.search(tuple(first["namespace"]), query="document", limit=25)
        assert len(hits) == first["chunk_count"]
        assert all(hit.value["page"] == 2 and hit.value["content_hash"] == "hash" for hit in hits)
        rows = store.conn.execute("SELECT COUNT(*) FROM store_vectors").fetchone()[0]
        embed.fail = True
        with pytest.raises(RuntimeError, match="provider unavailable"):
            replace_attachment_generation(store, text="replacement", **source)
        assert store.get(("document_active", "Board"), "attachment").value == first
        assert store.conn.execute("SELECT COUNT(*) FROM store_vectors").fetchone()[0] == rows
        embed.fail = False
        embed.invalid = True
        with pytest.raises(ValueError, match="dimension"):
            replace_attachment_generation(store, text="replacement", **source)
        assert store.get(("document_active", "Board"), "attachment").value == first
        assert store.conn.execute("SELECT COUNT(*) FROM store_vectors").fetchone()[0] == rows
        embed.invalid = False
        second = replace_attachment_generation(store, text="replacement", **source)
        assert second["generation"] != first["generation"]
        assert store.get(("document_active", "Board"), "attachment").value == second
        delete_attachment_generation(store, first)
        assert not store.search(tuple(first["namespace"]), query="document")
        assert store.search(tuple(second["namespace"]), query="document")
        assert store.conn.execute("SELECT COUNT(*) FROM store_vectors").fetchone()[0] == second["chunk_count"]
        for invalid in [{**source, "page": 0}, {**source, "attachment_uid": ""}]:
            with pytest.raises(ValueError):
                replace_attachment_generation(store, text="text", **invalid)
        with pytest.raises(ValueError):
            replace_attachment_generation(store, text=" ", **source)
        with pytest.raises(ValueError):
            delete_attachment_generation(store, {**second, "chunk_count": 10_000})


def test_staging_never_changes_the_active_pointer(tmp_path):
    source = dict(
        board_uid="board",
        card_uid="card",
        attachment_uid="attachment",
        content_hash="hash",
        fingerprint="fingerprint",
        splitter=DocumentSplitterSettings(chunk_size=64, chunk_overlap=8),
    )
    with open_document_store(tmp_path / "stage.sqlite", FixtureEmbeddings(), dimensions=3) as store:
        first = replace_attachment_generation(store, text="prior searchable text", **source)
        staged = replace_attachment_generation(store, text="replacement text", publish_pointer=False, **source)
        assert store.get(("document_active", "board"), "attachment").value == first
        assert store.search(tuple(staged["namespace"]), query="replacement", limit=1)
        delete_attachment_generation(store, staged)
        assert store.get(("document_active", "board"), "attachment").value == first
        assert not store.search(tuple(staged["namespace"]), query="replacement", limit=1)
