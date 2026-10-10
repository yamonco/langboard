from uuid import uuid4
import pytest
from langchain_core.embeddings import Embeddings
from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings
from langboard_shared.tasks.docling.DocumentSqliteStore import (
    open_document_store,
    open_sqlite_vector_store,
    remove_document_generation,
)
from langboard_shared.tasks.docling.DocumentVectorGeneration import replace_attachment_generation
from langboard_shared.tasks.docling.DocumentVectorStore import stage_vector_generation


class Fixture(Embeddings):
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [float("alpha" in text), float("beta" in text), 0.1]


def test_new_and_legacy_generations_survive_reopen_and_cleanup_independently(tmp_path):
    fingerprint = "a" * 64
    path = tmp_path / (fingerprint + ".sqlite")
    with open_document_store(path, Fixture(), dimensions=3) as store:
        legacy = replace_attachment_generation(
            store,
            board_uid="board",
            card_uid="card",
            attachment_uid="legacy",
            content_hash="hash",
            fingerprint=fingerprint,
            text="alpha legacy",
            splitter=DocumentSplitterSettings(),
            publish_pointer=False,
        )
    with open_sqlite_vector_store(path, Fixture(), dimensions=3) as store:
        pointer = stage_vector_generation(
            store,
            source=dict(
                board_uid="board",
                card_uid="card",
                attachment_uid="new",
                content_hash="hash",
                embedding_fingerprint=fingerprint,
            ),
            text="alpha 한글 日本語 中文",
            splitter=DocumentSplitterSettings(),
            storage={"type": "sqlite"},
        )
        other = str(uuid4())
        store.add_texts(["beta private"], [{"board_uid": "other"}], ids=[other])
        hits = store.similarity_search("alpha", k=5, filter={"board_uid": "board"})
        assert len(hits) == 1 and hits[0].id == pointer["chunk_ids"][0]
    with open_sqlite_vector_store(path, Fixture(), dimensions=3) as store:
        assert store.get_by_ids(pointer["chunk_ids"])[0].page_content == "alpha 한글 日本語 中文"
    remove_document_generation(tmp_path, pointer)
    remove_document_generation(tmp_path, pointer)
    with open_sqlite_vector_store(path, Fixture(), dimensions=3) as store:
        assert not store.get_by_ids(pointer["chunk_ids"])
        assert store.get_by_ids([other])
        assert store.store.get(tuple(legacy["namespace"]), "0") is not None
    remove_document_generation(tmp_path, legacy)
    with open_document_store(path, Fixture(), dimensions=3) as store:
        assert store.get(tuple(legacy["namespace"]), "0") is None


def test_failed_embedding_never_replaces_existing_chunks(tmp_path):
    path = tmp_path / "fixture.sqlite"
    identifier = str(uuid4())
    with open_sqlite_vector_store(path, Fixture(), dimensions=3) as store:
        store.add_texts(["alpha"], ids=[identifier])

    class Failed(Fixture):
        def embed_documents(self, texts):
            raise RuntimeError("fixture provider unavailable")

    with open_sqlite_vector_store(path, Failed(), dimensions=3) as store:
        with pytest.raises(RuntimeError):
            store.add_texts(["beta"], ids=[identifier])
        assert store.get_by_ids([identifier])[0].page_content == "alpha"
        with pytest.raises(ValueError):
            store.delete(ids=["not-a-uuid"])
        with pytest.raises(ValueError):
            store.similarity_search("alpha", k=1000)
