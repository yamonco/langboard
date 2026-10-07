"""Official LangChain VectorStore integration; source pointers stay in Langboard."""

from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import uuid4
from .DocumentSplitter import split_document
from .DocumentVectorGeneration import MAX_ATTACHMENT_CHUNKS


if TYPE_CHECKING:
    from langchain_core.vectorstores import VectorStore
    from .DocumentRetrievalSettings import DocumentRetrievalSettings


@contextmanager
def open_qdrant_store(
    settings: "DocumentRetrievalSettings", embeddings, fingerprint: str, allowed_urls: set[str], *, create=True
):
    """Connect only to an explicitly approved endpoint, using the official integration."""
    import re
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient, models
    from .DocumentEmbedding import validated_embeddings

    endpoint = str(settings.external_url).rstrip("/")
    if endpoint not in {url.strip().rstrip("/") for url in allowed_urls if url.strip()}:
        raise ValueError("Vector endpoint must be approved in DOCUMENT_VECTOR_ALLOWED_BASE_URLS")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid embedding fingerprint")
    client = QdrantClient(
        url=endpoint,
        api_key=settings.external_api_key.get_secret_value() if settings.external_api_key else None,
        timeout=settings.timeout_seconds,
    )
    try:
        collection = "langboard_documents_" + fingerprint
        if not client.collection_exists(collection):
            if not create:
                yield None
                return
            try:
                client.create_collection(
                    collection,
                    vectors_config=models.VectorParams(size=settings.dimensions, distance=models.Distance.COSINE),
                )
            except Exception:
                # Another worker may have created it. Still validate its dimensions below.
                if not client.collection_exists(collection):
                    raise
        vectors = client.get_collection(collection).config.params.vectors
        if (
            not isinstance(vectors, models.VectorParams)
            or vectors.size != settings.dimensions
            or vectors.distance != models.Distance.COSINE
        ):
            raise ValueError("Vector collection does not match the recorded embedding configuration")
        yield QdrantVectorStore(
            client=client,
            collection_name=collection,
            embedding=validated_embeddings(embeddings, settings.dimensions) if embeddings is not None else None,
            validate_embeddings=embeddings is not None,
            validate_collection_config=False,
        )
    finally:
        client.close()


@contextmanager
def open_document_vector_store(
    settings, embeddings, fingerprint: str, directory, allowed_urls: set[str], *, create=True
):
    """Keep backend connection details outside MCP and document processing."""
    import re
    from .DocumentSqliteStore import open_sqlite_vector_store

    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid embedding fingerprint")
    if settings.store == "sqlite":
        path = directory / (fingerprint + ".sqlite")
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        elif not path.is_file():
            yield None
            return
        context = open_sqlite_vector_store(
            path, embeddings, dimensions=settings.dimensions, timeout_seconds=settings.timeout_seconds
        )
    elif settings.store == "qdrant":
        context = open_qdrant_store(settings, embeddings, fingerprint, allowed_urls, create=create)
    else:
        raise ValueError("Unsupported vector storage")
    with context as store:
        yield store


def document_source_filter(storage: dict, source: dict):
    """Translate exact source constraints to the official backend filter format."""
    if storage.get("type") == "sqlite":
        return source
    if storage.get("type") != "qdrant":
        raise ValueError("Unsupported vector storage")
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(key="metadata." + key, match=models.MatchValue(value=value))
            for key, value in source.items()
        ]
    )


def stage_vector_generation(store: "VectorStore", *, source: dict, text: str, splitter, storage: dict) -> dict:
    """No active pointer changes until the caller's authoritative source fence commits."""
    if not all(
        isinstance(source.get(key), str) and source[key]
        for key in ("board_uid", "card_uid", "attachment_uid", "content_hash", "embedding_fingerprint")
    ):
        raise ValueError("Complete authoritative attachment source is required")
    if not text.strip():
        raise ValueError("An empty transcription cannot replace a searchable generation")
    generation = uuid4().hex
    chunks = split_document(text, splitter, metadata={**source, "generation": generation})
    if not 1 <= len(chunks) <= MAX_ATTACHMENT_CHUNKS:
        raise ValueError("Attachment exceeds the embedding chunk limit")
    ids = [str(uuid4()) for _ in chunks]
    pointer = {**source, "generation": generation, "chunk_count": len(chunks), "chunk_ids": ids, "storage": storage}
    try:
        returned = store.add_documents(chunks, ids=ids)
        if returned != ids:
            raise ValueError("Vector store did not preserve the requested chunk identifiers")
    except Exception:
        store.delete(ids=ids)
        raise
    return pointer


def delete_vector_generation(store: "VectorStore", pointer: dict) -> None:
    ids = pointer.get("chunk_ids")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_ATTACHMENT_CHUNKS
        or not all(isinstance(i, str) and i for i in ids)
    ):
        raise ValueError("Invalid recorded chunk identifiers")
    store.delete(ids=ids)
