"""Embed only a queued, current transcription snapshot; never scan existing attachments."""

from json import loads
from ...core.broker import Broker
from ...core.routing import SocketTopic
from ...domain.models import CardMetadata
from ...domain.models.InternalBot import InternalBotType
from ...domain.services import DomainService
from ...Env import Env
from .DocumentEmbedding import create_document_embeddings, resolve_embedding_snapshot, validate_embedding_config
from .DocumentSqliteStore import open_document_store
from .DocumentVectorGeneration import delete_attachment_generation, embedding_fingerprint, replace_attachment_generation


@Broker.wrap_async_task_decorator
async def index_transcribed_attachment(request: str):
    service = DomainService()
    try:
        payload = loads(request)
        if isinstance(payload, dict):
            embed_transcription(service, payload.get("attachment_uid"), payload.get("generation"))
    finally:
        service.close()


def embed_transcription(service, attachment_uid: str, generation: str) -> None:
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
    try:
        if not binding or binding.bot_type != InternalBotType.DocumentEmbedding:
            raise ValueError("Embedding binding is unavailable")
        private = resolve_embedding_snapshot(snapshot, binding.value)
        config, settings = validate_embedding_config(private)
        if settings.store != "sqlite":
            raise ValueError("External vector storage is not connected yet")
        allowed = set(Env.get_from_env("MODEL_PROVIDER_ALLOWED_BASE_URLS", "").split(","))
        embeddings = create_document_embeddings(private, allowed)
        fingerprint = embedding_fingerprint(
            provider=config["base_url"], model=config["model_name"], dimensions=settings.dimensions, version="v1"
        )
        if (
            old.get("status") == "indexed"
            and old.get("source_generation") == generation
            and (old.get("pointer") or {}).get("embedding_fingerprint") == fingerprint
        ):
            return
        directory = Env.DATA_DIR / "document-retrieval"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (fingerprint + ".sqlite")
        # No PostgreSQL row lock is held during remote inference.
        with open_document_store(
            path, embeddings, dimensions=settings.dimensions, timeout_seconds=settings.timeout_seconds
        ) as store:
            pointer = replace_attachment_generation(
                store,
                board_uid=project.get_uid(),
                card_uid=card.get_uid(),
                attachment_uid=attachment_uid,
                content_hash=content_hash,
                fingerprint=fingerprint,
                text=(document.get("content") or {}).get("markdown", ""),
                splitter=settings.splitter,
                publish_pointer=False,
            )
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
                delete_attachment_generation(store, pointer)
                raise
            if not committed:
                delete_attachment_generation(store, pointer)
                return
            prior = old.get("pointer")
            if isinstance(prior, dict) and prior.get("embedding_fingerprint") == fingerprint:
                try:
                    delete_attachment_generation(store, prior)
                except Exception:
                    # The new source pointer is already committed. Cleanup cannot downgrade it.
                    pass
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
