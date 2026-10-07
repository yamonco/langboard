"""LangChain boundary for the existing official SQLite store; no custom SQL index."""

from typing import Iterable
from uuid import UUID, uuid4
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langgraph.store.base import GetOp, PutOp
from .DocumentVectorGeneration import MAX_ATTACHMENT_CHUNKS


class DocumentSqliteVectorStore(VectorStore):
    namespace = ("document_vectors",)

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _ids(ids):
        if not isinstance(ids, list) or len(ids) > MAX_ATTACHMENT_CHUNKS:
            raise ValueError("Invalid chunk identifier count")
        if any(not isinstance(value, str) or str(UUID(value)) != value for value in ids):
            raise ValueError("Canonical UUID chunk identifiers required")
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk identifiers")
        return ids

    def add_texts(self, texts: Iterable[str], metadatas=None, *, ids=None, **kwargs):
        if kwargs:
            raise ValueError("Unsupported SQLite add options")
        texts = list(texts)
        ids = self._ids(ids if ids is not None else [str(uuid4()) for _ in texts])
        metadatas = metadatas if metadatas is not None else [{} for _ in texts]
        if len(texts) != len(ids) or len(texts) != len(metadatas):
            raise ValueError("Text, metadata and identifier counts differ")
        if any(not isinstance(metadata, dict) or "text" in metadata for metadata in metadatas):
            raise ValueError("Metadata cannot replace document text")
        self.store.batch(
            [
                PutOp(self.namespace, identifier, {**metadata, "text": text})
                for identifier, text, metadata in zip(ids, texts, metadatas)
            ]
        )
        return ids

    def delete(self, ids=None, **kwargs):
        if kwargs or ids is None:
            raise ValueError("Explicit chunk identifiers required for deletion")
        self.store.batch([PutOp(self.namespace, identifier, None) for identifier in self._ids(ids)])
        return True

    def get_by_ids(self, ids):
        values = self.store.batch([GetOp(self.namespace, identifier) for identifier in self._ids(ids)])
        return [self._document(value) for value in values if value is not None]

    @staticmethod
    def _document(item):
        return Document(
            id=item.key, page_content=item.value["text"], metadata={k: v for k, v in item.value.items() if k != "text"}
        )

    def similarity_search(self, query, k=4, *, filter=None, **kwargs):
        if kwargs or type(k) is not int or not 1 <= k <= 100:
            raise ValueError("Unsupported or unbounded SQLite search options")
        return [self._document(item) for item in self.store.search(self.namespace, query=query, filter=filter, limit=k)]

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, *, store=None, **kwargs):
        if store is None:
            raise ValueError("An opened, embedding-configured SQLite store is required")
        result = cls(store)
        result.add_texts(texts, metadatas=metadatas, **kwargs)
        return result
