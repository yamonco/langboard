"""Open the official LangGraph store with LangChain embeddings and SQLite lifecycle guarantees."""

import re
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
    from langgraph.store.sqlite import SqliteStore
    from .DocumentEmbedding import validated_embeddings

    if type(dimensions) is not int or not 1 <= dimensions <= 65536:
        raise ValueError("dimensions must be an integer from 1 to 65536")
    if type(timeout_seconds) not in (int, float) or not isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 30:
        raise ValueError("SQLite lock timeout must be from 1 to 30 seconds")

    connection = sqlite3.connect(path, timeout=timeout_seconds, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        store = SqliteStore(
            connection,
            index={
                "dims": dimensions,
                "embed": validated_embeddings(embeddings, dimensions),
                "fields": ["text"],
                "distance_type": "cosine",
            },
        )
        store.setup()
        # setup performs migration DML. End it before the store starts its own transaction.
        connection.commit()
        yield store
    finally:
        connection.close()


def remove_document_generation(directory: Path, pointer: dict) -> None:
    """Remove one recorded generation without resolving an embedding provider.

    Opening an existing database without an index avoids inference, credential
    access and vector-extension loading. The official delete batch still removes
    vectors through the store's foreign-key cascade.
    """
    from langgraph.store.sqlite import SqliteStore
    from .DocumentVectorGeneration import delete_attachment_generation

    fingerprint = pointer.get("embedding_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid embedding fingerprint")
    path = directory / (fingerprint + ".sqlite")
    if not path.is_file():
        return
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        store = SqliteStore(connection)
        store.setup()
        connection.commit()
        if "chunk_ids" in pointer:
            from .DocumentSqliteVectorStore import DocumentSqliteVectorStore
            from .DocumentVectorStore import delete_vector_generation

            delete_vector_generation(DocumentSqliteVectorStore(store), pointer)
        else:
            delete_attachment_generation(store, pointer)
    finally:
        connection.close()


@contextmanager
def open_sqlite_vector_store(path: Path, embeddings: "Embeddings", *, dimensions: int, timeout_seconds: float = 10.0):
    from .DocumentSqliteVectorStore import DocumentSqliteVectorStore

    with open_document_store(path, embeddings, dimensions=dimensions, timeout_seconds=timeout_seconds) as store:
        yield DocumentSqliteVectorStore(store)
