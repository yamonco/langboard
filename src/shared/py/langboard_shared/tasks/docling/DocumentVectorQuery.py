"""Bounded generation-scoped queries; callers own current authorization checks."""

from math import isfinite
from .DocumentVectorGeneration import MAX_ATTACHMENT_CHUNKS
from .DocumentVectorStore import document_source_filter


def search_vector_generation(store, pointer: dict, query: str, settings, *, max_tokens: int = 4000) -> list[dict]:
    import tiktoken

    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("Query must contain 1..1000 characters")
    if type(max_tokens) is not int or not 128 <= max_tokens <= 4000:
        raise ValueError("Invalid excerpt token budget")
    ids = pointer.get("chunk_ids")
    fields = ("board_uid", "card_uid", "attachment_uid", "content_hash", "embedding_fingerprint", "generation")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_ATTACHMENT_CHUNKS
        or not all(isinstance(i, str) and i for i in ids)
    ):
        raise ValueError("Reindex this attachment before vector retrieval")
    if not all(isinstance(pointer.get(key), str) and pointer[key] for key in fields):
        raise ValueError("Incomplete vector source")
    source = {key: pointer[key] for key in fields}
    filter = document_source_filter(pointer.get("storage") or {}, source)
    if settings.search_type == "mmr":
        if settings.score_threshold is not None:
            raise ValueError("MMR with a score threshold is not supported")
        documents = store.max_marginal_relevance_search(
            query, k=settings.k, fetch_k=settings.fetch_k, lambda_mult=settings.lambda_mult, filter=filter
        )
        hits = [(document, None) for document in documents]
    else:
        hits = store.similarity_search_with_score(query, k=settings.k, filter=filter)
    encoding = tiktoken.get_encoding("cl100k_base")
    remaining = min(max_tokens, settings.max_return_tokens)
    result = []
    for document, score in hits[: settings.k]:
        metadata = document.metadata
        identifier = document.id or metadata.get("_id")
        if str(identifier) not in ids or any(metadata.get(key) != value for key, value in source.items()):
            continue
        if score is not None and (type(score) not in (int, float) or not isfinite(score)):
            continue
        if settings.score_threshold is not None and (score is None or score < settings.score_threshold):
            continue
        tokens = encoding.encode(document.page_content, disallowed_special=())
        if not remaining:
            break
        content = encoding.decode(tokens[:remaining])
        remaining -= min(len(tokens), remaining)
        pages = metadata.get("pages")
        pages = sorted({page for page in pages if type(page) is int and page > 0}) if isinstance(pages, list) else []
        result.append(
            {
                "chunk_id": str(identifier),
                "content": content,
                "source": source,
                **({"pages": pages} if pages else {}),
                **({"page": metadata["page"]} if type(metadata.get("page")) is int and metadata["page"] > 0 else {}),
            }
        )
    return result
