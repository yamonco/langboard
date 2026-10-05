"""Attachment generation publication through the official store's atomic batch."""

from hashlib import sha256
from json import dumps
from typing import TYPE_CHECKING
from uuid import uuid4
from .DocumentSplitter import DocumentSplitterSettings, split_document


if TYPE_CHECKING:
    from langgraph.store.sqlite import SqliteStore


MAX_ATTACHMENT_CHUNKS = 2048


def embedding_fingerprint(*, provider: str, model: str, dimensions: int, version: str) -> str:
    """Credentials never identify an index; provider endpoint/model/dimension do."""
    return sha256(dumps([provider, model, dimensions, version], ensure_ascii=False).encode()).hexdigest()


def replace_attachment_generation(
    store: "SqliteStore",
    *,
    board_uid: str,
    card_uid: str,
    attachment_uid: str,
    content_hash: str,
    fingerprint: str,
    text: str,
    splitter: DocumentSplitterSettings,
    page: int | None = None,
) -> dict:
    """Caller must lock and revalidate the current, readable attachment before publishing.

    Source IDs come from authoritative records, never model-generated metadata.
    Store.batch rolls back both chunks and pointer when embedding fails. Older
    generations remain available until the caller completes its lifecycle fence.
    """
    from langgraph.store.base import PutOp

    if not all(
        isinstance(value, str) and value for value in (board_uid, card_uid, attachment_uid, content_hash, fingerprint)
    ):
        raise ValueError("Complete authoritative attachment source is required")
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError("Page must be a positive integer when known")
    if not text.strip():
        raise ValueError("An empty transcription cannot replace a searchable generation")
    generation = uuid4().hex
    source = {
        "board_uid": board_uid,
        "card_uid": card_uid,
        "attachment_uid": attachment_uid,
        "content_hash": content_hash,
        "embedding_fingerprint": fingerprint,
        "generation": generation,
    }
    if page is not None:
        source["page"] = page
    chunks = split_document(text, splitter, metadata=source)
    if not 1 <= len(chunks) <= MAX_ATTACHMENT_CHUNKS:
        raise ValueError("Attachment exceeds the embedding chunk limit")
    namespace = ("documents", board_uid, attachment_uid, fingerprint, generation)
    pointer = {**source, "chunk_count": len(chunks), "namespace": list(namespace)}
    store.batch(
        [
            *(
                PutOp(namespace, str(index), {**chunk.metadata, "text": chunk.page_content})
                for index, chunk in enumerate(chunks)
            ),
            PutOp(("document_active", board_uid), attachment_uid, pointer, index=False),
        ]
    )
    return pointer


def delete_attachment_generation(store: "SqliteStore", pointer: dict) -> None:
    """Delete only a server-recorded generation, including its cascading vectors."""
    from langgraph.store.base import PutOp

    count = pointer.get("chunk_count")
    namespace = pointer.get("namespace")
    if type(count) is not int or not 1 <= count <= MAX_ATTACHMENT_CHUNKS:
        raise ValueError("Invalid generation chunk count")
    if (
        not isinstance(namespace, list)
        or len(namespace) != 5
        or namespace[0] != "documents"
        or not all(isinstance(value, str) and value for value in namespace)
        or namespace
        != [
            "documents",
            pointer.get("board_uid"),
            pointer.get("attachment_uid"),
            pointer.get("embedding_fingerprint"),
            pointer.get("generation"),
        ]
    ):
        raise ValueError("Invalid generation namespace")
    store.batch([PutOp(tuple(namespace), str(index), None) for index in range(count)])
