"""Open the official LangGraph store with LangChain embeddings and SQLite lifecycle guarantees."""

import sqlite3
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Iterator


if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langgraph.store.sqlite import SqliteStore


@contextmanager
def open_document_store(
    path: Path, embeddings: "Embeddings", *, dimensions: int, timeout_seconds: float = 10.0
) -> Iterator["SqliteStore"]:
    """The caller supplies a server-owned volume path, never a client-selected path.

    Each process gets its own connection. The official store owns indexing,
    similarity search, metadata filtering and transactions. Current board/card
    authorization must be checked by the caller; namespaces are not an ACL.
    """
    from langchain_core.embeddings import Embeddings
    from langgraph.store.sqlite import SqliteStore

    if type(dimensions) is not int or not 1 <= dimensions <= 65536:
        raise ValueError("dimensions must be an integer from 1 to 65536")
    if type(timeout_seconds) not in (int, float) or not isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 30:
        raise ValueError("SQLite lock timeout must be from 1 to 30 seconds")

    class ValidatedEmbeddings(Embeddings):
        """Reject invalid upstream vectors before the official transaction commits."""

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            vectors = embeddings.embed_documents(texts)
            if len(vectors) != len(texts):
                raise ValueError("Embedding provider returned an unexpected vector count")
            return [self._validate(vector) for vector in vectors]

        def embed_query(self, text: str) -> list[float]:
            return self._validate(embeddings.embed_query(text))

        @staticmethod
        def _validate(vector: list[float]) -> list[float]:
            if len(vector) != dimensions or any(
                type(value) not in (int, float) or not isfinite(value) for value in vector
            ):
                raise ValueError("Embedding vector dimension or numeric values do not match the configured model")
            return vector

    connection = sqlite3.connect(path, timeout=timeout_seconds, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        store = SqliteStore(
            connection,
            index={"dims": dimensions, "embed": ValidatedEmbeddings(), "fields": ["text"], "distance_type": "cosine"},
        )
        store.setup()
        # setup performs migration DML. End it before the store starts its own transaction.
        connection.commit()
        yield store
    finally:
        connection.close()
