"""Embed only a queued, current transcription snapshot; never scan existing attachments."""

from json import dumps, loads
from sqlite3 import OperationalError
from ...core.broker import Broker, TaskParameters
from ...core.routing import SocketTopic
from ...domain.models import CardMetadata
from ...domain.models.InternalBot import InternalBotType
from ...domain.services import DomainService
from ...Env import Env
from .DocumentEmbedding import create_document_embeddings, resolve_embedding_snapshot, validate_embedding_config
from .DocumentRetrievalSettings import DocumentRetrievalSettings
from .DocumentSqliteStore import open_sqlite_vector_store, remove_document_generation
from .DocumentVectorGeneration import embedding_fingerprint
from .DocumentVectorStore import delete_vector_generation, open_qdrant_store, stage_vector_generation


@Broker.wrap_async_task_decorator
async def index_transcribed_attachment(request: str):
    service = DomainService()
    try:
        payload = loads(request)
        if isinstance(payload, dict):
            embed_transcription(
                service, payload.get("attachment_uid"), payload.get("generation"), payload.get("request_uid")
            )
    finally:
        service.close()


@Broker.wrap_async_task_decorator({"autoretry_for": (OperationalError,), "retry_backoff": True, "max_retries": 3})
async def remove_attachment_embedding(request: str):
    """Only the committed attachment lifecycle supplies this server-owned pointer."""
    pointer = loads(request)
    if not isinstance(pointer, dict):
        raise ValueError("A recorded embedding pointer is required")
    storage = pointer.get("storage") or {}
    if storage.get("type", "sqlite") == "sqlite":
        remove_document_generation(Env.DATA_DIR / "document-retrieval", pointer)
        return
    if storage.get("type") != "qdrant":
        raise ValueError("Unsupported recorded vector storage")
    service = DomainService()
    try:
        binding = service.internal_bot.get_by_id_like(storage.get("binding_uid"))
        if not binding or binding.bot_type != InternalBotType.DocumentEmbedding:
            raise ValueError("Recorded vector binding is unavailable")
        _, current = validate_embedding_config(binding.value)
        if str(current.external_url).rstrip("/") != storage.get("endpoint"):
            raise ValueError("Recorded vector endpoint changed; cleanup requires the original connection")
        settings = DocumentRetrievalSettings(
            store="qdrant",
            external_url=current.external_url,
            external_api_key=current.external_api_key,
            dimensions=storage["dimensions"],
        )
        allowed = set(Env.get_from_env("DOCUMENT_VECTOR_ALLOWED_BASE_URLS", "").split(","))
        with open_qdrant_store(settings, None, pointer["embedding_fingerprint"], allowed, create=False) as store:
            if store is not None:
                delete_vector_generation(store, pointer)
    finally:
        service.close()


def embed_transcription(service, attachment_uid: str, generation: str, request_uid: str | None = None) -> None:
    if not isinstance(attachment_uid, str) or not isinstance(generation, str):
        return
    attachment = service.card_attachment.get_by_id_like(attachment_uid)
    if not attachment or attachment.deleted_at is not None:
        return
    card = service.card.get_by_id_like(attachment.card_id)
    if not card or card.is_linked_resource:
        return
    document = service.docling_metadata.get_document_by_attachment_uid(CardMetadata, card, attachment_uid)
    if not document or document.get("generation") != generation or document.get("status") != "indexed":
        return
    project = service.project.get_by_id_like(card.project_id)
    if not project:
        return
    snapshot = document.get("embedding_config")
    if not isinstance(snapshot, dict):
        return
    binding = service.internal_bot.get_by_id_like(snapshot.get("binding_uid"))
    content_hash = document.get("content_hash")
    old = document.get("embedding") or {}
    if request_uid is not None and old.get("request_uid") != request_uid:
        return
    try:
        if not binding or binding.bot_type != InternalBotType.DocumentEmbedding:
            raise ValueError("Embedding binding is unavailable")
        private = resolve_embedding_snapshot(snapshot, binding.value)
        config, settings = validate_embedding_config(private)
        allowed = set(Env.get_from_env("MODEL_PROVIDER_ALLOWED_BASE_URLS", "").split(","))
        embeddings = create_document_embeddings(private, allowed)
        fingerprint = embedding_fingerprint(
            provider=config["base_url"], model=config["model_name"], dimensions=settings.dimensions, version="v1"
        )
        if (
            old.get("status") == "indexed"
            and old.get("source_generation") == generation
            and (old.get("pointer") or {}).get("embedding_fingerprint") == fingerprint
            and ((old.get("pointer") or {}).get("storage") or {}).get("type", "sqlite") == settings.store
            and (
                settings.store == "sqlite"
                or ((old.get("pointer") or {}).get("storage") or {}).get("endpoint")
                == str(settings.external_url).rstrip("/")
            )
        ):
            return
        directory = Env.DATA_DIR / "document-retrieval"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (fingerprint + ".sqlite")
        # No PostgreSQL row lock is held during remote inference.
        vector_allowed = set(Env.get_from_env("DOCUMENT_VECTOR_ALLOWED_BASE_URLS", "").split(","))
        context = (
            open_sqlite_vector_store(
                path, embeddings, dimensions=settings.dimensions, timeout_seconds=settings.timeout_seconds
            )
            if settings.store == "sqlite"
            else open_qdrant_store(settings, embeddings, fingerprint, vector_allowed)
        )
        with context as store:
            source = dict(
                board_uid=project.get_uid(),
                card_uid=card.get_uid(),
                attachment_uid=attachment_uid,
                content_hash=content_hash,
                embedding_fingerprint=fingerprint,
            )
            storage = {"type": settings.store}
            if settings.store == "qdrant":
                storage.update(
                    endpoint=str(settings.external_url).rstrip("/"),
                    binding_uid=snapshot["binding_uid"],
                    dimensions=settings.dimensions,
                )
            pointer = stage_vector_generation(
                store,
                source=source,
                text=(document.get("content") or {}).get("markdown", ""),
                splitter=settings.splitter,
                storage=storage,
            )
            remove = delete_vector_generation
            try:
                committed = service.docling_metadata.publish_document_embedding(
                    card,
                    attachment_uid,
                    generation,
                    content_hash,
                    {"status": "indexed", "pointer": pointer, "source_generation": generation},
                    expected_embedding=old,
                )
            except Exception:
                remove(store, pointer)
                raise
            if not committed:
                remove(store, pointer)
                return
            prior = old.get("pointer")
            if (
                isinstance(prior, dict)
                and prior.get("embedding_fingerprint") == fingerprint
                and (prior.get("storage") or {"type": "sqlite"}) == pointer.get("storage")
            ):
                try:
                    if settings.store == "sqlite" and "namespace" in prior:
                        remove_document_generation(directory, prior)
                    else:
                        remove(store, prior)
                except Exception:
                    # The new source pointer is already committed. Cleanup cannot downgrade it.
                    _queue_previous_generation(prior)
            elif isinstance(prior, dict) and ("chunk_ids" in prior or "namespace" in prior):
                # Different models/stores must clean up using the recorded old connection.
                _queue_previous_generation(prior)
    except Exception:
        # Provider exceptions may contain credentials or document text. Never publish raw errors.
        service.docling_metadata.publish_document_embedding(
            card,
            attachment_uid,
            generation,
            content_hash,
            {**old, "status": "failed", "error": "Embedding failed; the previous searchable generation is retained"},
            expected_embedding=old,
        )
    service.docling_metadata.publish_update(CardMetadata, card, SocketTopic.BoardCard)


def _queue_previous_generation(pointer: dict) -> None:
    """Best-effort dispatch after publication; never downgrade the new generation."""
    try:
        args, kwargs = TaskParameters(dumps(pointer)).pack()
        Broker.celery.send_task(
            "langboard_shared.tasks.docling.DocumentEmbeddingTask.remove_attachment_embedding",
            args=args,
            kwargs=kwargs,
        )
    except Exception:
        # A durable outbox is still needed for broker outages.
        pass
