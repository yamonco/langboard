"""Source fencing and queue failure retain searchable generations without leaking secrets."""

import os


os.environ.setdefault("PROJECT_NAME", "langboard")
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.tasks.docling import DoclingMetadataTask as transcription
from langboard_shared.tasks.docling import DocumentEmbeddingTask as task


def fixture(monkeypatch, tmp_path):
    document = {
        "generation": "current",
        "status": "indexed",
        "content_hash": "hash",
        "content": {"markdown": "document"},
        "embedding_config": {"binding_uid": "binding"},
        "embedding": {"status": "indexed", "pointer": {"generation": "old"}},
    }
    metadata = Mock()
    metadata.get_document_by_attachment_uid.return_value = document
    metadata.publish_document_embedding.return_value = True
    card = SimpleNamespace(project_id=123, is_linked_resource=False, get_uid=lambda: "card-uid")
    attachment = SimpleNamespace(card_id=4, deleted_at=None)
    binding = SimpleNamespace(bot_type=InternalBotType.DocumentEmbedding, value="private")
    service = SimpleNamespace(
        card_attachment=SimpleNamespace(get_by_id_like=Mock(return_value=attachment)),
        card=SimpleNamespace(get_by_id_like=Mock(return_value=card)),
        project=SimpleNamespace(get_by_id_like=Mock(return_value=SimpleNamespace(get_uid=lambda: "board-uid"))),
        internal_bot=SimpleNamespace(get_by_id_like=Mock(return_value=binding)),
        docling_metadata=metadata,
    )
    monkeypatch.setattr(
        task, "Env", SimpleNamespace(DATA_DIR=tmp_path, get_from_env=lambda *_: "https://fixture.invalid")
    )
    monkeypatch.setattr(task, "resolve_embedding_snapshot", Mock(return_value="resolved"))
    monkeypatch.setattr(
        task,
        "validate_embedding_config",
        Mock(
            return_value=(
                {"base_url": "https://fixture.invalid", "model_name": "model"},
                SimpleNamespace(store="sqlite", dimensions=3, timeout_seconds=2, splitter=object()),
            )
        ),
    )
    monkeypatch.setattr(task, "create_document_embeddings", Mock(return_value=object()))
    monkeypatch.setattr(task, "open_document_vector_store", Mock(return_value=nullcontext(object())))
    monkeypatch.setattr(
        task,
        "stage_vector_generation",
        Mock(return_value={"generation": "new", "embedding_fingerprint": "new-fingerprint"}),
    )
    monkeypatch.setattr(task, "delete_vector_generation", Mock())
    return service, document, attachment


@pytest.mark.parametrize("invalid", ["deleted", "stale", "missing-board"])
def test_invalid_sources_never_send_document(monkeypatch, tmp_path, invalid):
    service, document, attachment = fixture(monkeypatch, tmp_path)
    if invalid == "deleted":
        attachment.deleted_at = "deleted"
    if invalid == "stale":
        document["generation"] = "newer"
    if invalid == "missing-board":
        service.project.get_by_id_like.return_value = None
    task.embed_transcription(service, "attachment", "current")
    task.create_document_embeddings.assert_not_called()
    task.stage_vector_generation.assert_not_called()
    service.docling_metadata.publish_document_embedding.assert_not_called()


def test_staged_generation_uses_public_board_uid_and_is_removed_on_failed_publication(monkeypatch, tmp_path):
    service, _, _ = fixture(monkeypatch, tmp_path)
    service.docling_metadata.publish_document_embedding.return_value = False
    task.embed_transcription(service, "attachment", "current")
    args = task.stage_vector_generation.call_args.kwargs
    assert args["source"]["board_uid"] == "board-uid"
    assert args["storage"] == {"type": "sqlite"}
    task.delete_vector_generation.assert_called_once()
    assert (
        service.docling_metadata.publish_document_embedding.call_args.kwargs["expected_embedding"]["pointer"][
            "generation"
        ]
        == "old"
    )


def test_replaced_explicit_request_never_starts_inference(monkeypatch, tmp_path):
    service, document, _ = fixture(monkeypatch, tmp_path)
    document["embedding"]["request_uid"] = "new-request"
    task.embed_transcription(service, "attachment", "current", "old-request")
    task.create_document_embeddings.assert_not_called()
    service.docling_metadata.publish_document_embedding.assert_not_called()


def test_provider_failure_retains_prior_pointer_and_redacts_error(monkeypatch, tmp_path):
    service, _, _ = fixture(monkeypatch, tmp_path)
    task.stage_vector_generation.side_effect = RuntimeError("secret-key and confidential document")
    task.embed_transcription(service, "attachment", "current")
    failure = service.docling_metadata.publish_document_embedding.call_args.args[-1]
    assert failure["status"] == "failed"
    assert failure["pointer"]["generation"] == "old"
    assert "secret-key" not in failure["error"]
    assert "confidential" not in failure["error"]


def test_queue_outage_and_metadata_outage_never_downgrade_transcription(monkeypatch):
    service = SimpleNamespace(docling_metadata=Mock())
    service.docling_metadata.get_document_by_attachment_uid.side_effect = RuntimeError("metadata unavailable")
    monkeypatch.setattr(transcription.Broker.celery, "send_task", Mock(side_effect=RuntimeError("broker unavailable")))
    transcription._queue_embedding(service, object(), "attachment", "generation")
    service.docling_metadata.mark_document_failed.assert_not_called()


def test_database_publication_error_removes_staged_vectors(monkeypatch, tmp_path):
    service, _, _ = fixture(monkeypatch, tmp_path)
    service.docling_metadata.publish_document_embedding.side_effect = [RuntimeError("database failure"), True]
    task.embed_transcription(service, "attachment", "current")
    task.delete_vector_generation.assert_called_once()
    assert service.docling_metadata.publish_document_embedding.call_count == 2


def test_missing_binding_reports_safe_failure_without_inference(monkeypatch, tmp_path):
    service, _, _ = fixture(monkeypatch, tmp_path)
    service.internal_bot.get_by_id_like.return_value = None
    task.embed_transcription(service, "attachment", "current")
    task.create_document_embeddings.assert_not_called()
    assert service.docling_metadata.publish_document_embedding.call_args.args[-1]["status"] == "failed"


def test_qdrant_generation_publishes_backend_independent_ids_and_cleans_rejected_stage(monkeypatch, tmp_path):
    service, document, _ = fixture(monkeypatch, tmp_path)
    document["embedding_config"]["binding_uid"] = "binding"
    config, settings = task.validate_embedding_config.return_value
    settings.store = "qdrant"
    settings.external_url = "https://vectors.invalid"
    monkeypatch.setattr(task, "open_qdrant_store", Mock(return_value=nullcontext(object())))
    pointer = {"embedding_fingerprint": "new", "chunk_ids": ["chunk"], "storage": {"type": "qdrant"}}
    monkeypatch.setattr(task, "stage_vector_generation", Mock(return_value=pointer))
    monkeypatch.setattr(task, "delete_vector_generation", Mock())
    service.docling_metadata.publish_document_embedding.return_value = False
    task.embed_transcription(service, "attachment", "current")
    assert task.open_document_vector_store.call_args.args[0].store == "qdrant"
    task.stage_vector_generation.assert_called_once()
    task.delete_vector_generation.assert_called_once()
    source = task.stage_vector_generation.call_args.kwargs["source"]
    assert source["board_uid"] == "board-uid" and source["attachment_uid"] == "attachment"
    assert service.docling_metadata.publish_document_embedding.call_args.args[-1]["pointer"] == pointer


def test_sqlite_reindex_removes_legacy_only_after_pointer_commit(monkeypatch, tmp_path):
    from langboard_shared.tasks.docling.DocumentEmbedding import validated_embeddings
    from langboard_shared.tasks.docling.DocumentSplitter import DocumentSplitterSettings
    from langboard_shared.tasks.docling.DocumentSqliteStore import open_document_store, open_sqlite_vector_store
    from langboard_shared.tasks.docling.DocumentSqliteVectorStore_test import Fixture
    from langboard_shared.tasks.docling.DocumentVectorGeneration import (
        embedding_fingerprint,
        replace_attachment_generation,
    )
    from langboard_shared.tasks.docling.DocumentVectorStore import delete_vector_generation, stage_vector_generation

    service, document, _ = fixture(monkeypatch, tmp_path)
    config, settings = task.validate_embedding_config.return_value
    settings.splitter = DocumentSplitterSettings()
    fingerprint = embedding_fingerprint(
        provider=config["base_url"], model=config["model_name"], dimensions=3, version="v1"
    )
    directory = tmp_path / "document-retrieval"
    directory.mkdir()
    path = directory / (fingerprint + ".sqlite")
    with open_document_store(path, Fixture(), dimensions=3) as store:
        legacy = replace_attachment_generation(
            store,
            board_uid="board-uid",
            card_uid="card-uid",
            attachment_uid="attachment",
            content_hash="hash",
            fingerprint=fingerprint,
            text="alpha old",
            splitter=settings.splitter,
            publish_pointer=False,
        )
    document["embedding"] = {"status": "pending", "pointer": legacy}
    task.create_document_embeddings.return_value = validated_embeddings(Fixture(), 3)
    from langboard_shared.tasks.docling.DocumentVectorStore import open_document_vector_store

    monkeypatch.setattr(task, "open_document_vector_store", open_document_vector_store)
    monkeypatch.setattr(task, "stage_vector_generation", stage_vector_generation)
    monkeypatch.setattr(task, "delete_vector_generation", delete_vector_generation)
    service.docling_metadata.publish_document_embedding.return_value = False
    task.embed_transcription(service, "attachment", "current")
    with open_document_store(path, Fixture(), dimensions=3) as store:
        assert store.get(tuple(legacy["namespace"]), "0") is not None
    service.docling_metadata.publish_document_embedding.return_value = True
    task.embed_transcription(service, "attachment", "current")
    pointer = service.docling_metadata.publish_document_embedding.call_args.args[-1]["pointer"]
    assert pointer["storage"] == {"type": "sqlite"} and "namespace" not in pointer
    with open_sqlite_vector_store(path, Fixture(), dimensions=3) as store:
        assert store.get_by_ids(pointer["chunk_ids"])
        assert store.store.get(tuple(legacy["namespace"]), "0") is None


@pytest.mark.parametrize("publication", [True, False, "error"])
def test_changed_model_or_store_cleans_recorded_generation_only_after_publication(monkeypatch, tmp_path, publication):
    service, document, _ = fixture(monkeypatch, tmp_path)
    prior = {
        "generation": "previous",
        "embedding_fingerprint": "a" * 64,
        "chunk_ids": ["old"],
        "storage": {"type": "qdrant", "endpoint": "https://old.invalid", "binding_uid": "old-binding", "dimensions": 3},
    }
    document["embedding"]["pointer"] = prior
    queue = Mock()
    monkeypatch.setattr(task, "_queue_previous_generation", queue)
    service.docling_metadata.publish_document_embedding.return_value = publication is True
    if publication == "error":
        service.docling_metadata.publish_document_embedding.side_effect = [
            RuntimeError("publication unavailable"),
            True,
        ]
    task.embed_transcription(service, "attachment", "current")
    if publication is True:
        queue.assert_called_once_with(prior)
        task.delete_vector_generation.assert_not_called()
        assert service.docling_metadata.publish_document_embedding.call_args.args[-1]["status"] == "indexed"
    else:
        queue.assert_not_called()
        task.delete_vector_generation.assert_called_once()


def test_cleanup_dispatch_outage_cannot_downgrade_committed_generation(monkeypatch, tmp_path):
    service, document, _ = fixture(monkeypatch, tmp_path)
    document["embedding"]["pointer"] = {
        "generation": "previous",
        "embedding_fingerprint": "a" * 64,
        "namespace": ["documents", "board", "attachment", "fingerprint", "previous"],
    }
    monkeypatch.setattr(task.Broker.celery, "send_task", Mock(side_effect=RuntimeError("broker unavailable")))
    task.embed_transcription(service, "attachment", "current")
    assert service.docling_metadata.publish_document_embedding.call_count == 1
    assert service.docling_metadata.publish_document_embedding.call_args.args[-1]["status"] == "indexed"
