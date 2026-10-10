"""Historical imports must not consume current automatic VLM settings."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ...models import User
from .CardAttachmentService import CardAttachmentService
from .DoclingMetadataService import DoclingMetadataService


module = import_module("langboard_shared.domain.services.factory.CardAttachmentService")


def test_historical_pdf_dispatch_never_resolves_vlm_or_enqueues(monkeypatch):
    service = object.__new__(CardAttachmentService)
    metadata = Mock()
    provider = Mock()
    provider.get_document_vision_binding.side_effect = AssertionError("Historical imports must not resolve VLM")
    monkeypatch.setattr(service, "_get_service", lambda cls: metadata if cls is DoclingMetadataService else provider)
    enqueue = Mock()
    monkeypatch.setattr(service, "_queue_docling_index_task", enqueue)
    uploaded, activity, bot = Mock(), Mock(), Mock()
    monkeypatch.setattr(module.CardAttachmentPublisher, "uploaded", uploaded)
    monkeypatch.setattr(module.CardAttachmentActivityTask, "card_attachment_uploaded", activity)
    monkeypatch.setattr(module.CardAttachmentBotTask, "card_attachment_uploaded", bot)
    attachment = SimpleNamespace(filename="historical.pdf")
    service.dispatch_created(
        "author", "board", "card", attachment, include_bot=False, include_document_processing=False
    )
    provider.get_document_vision_binding.assert_not_called()
    metadata.queue_document.assert_not_called()
    enqueue.assert_not_called()
    uploaded.assert_called_once()
    activity.assert_called_once()
    bot.assert_not_called()


@pytest.mark.parametrize("queue_fails", [False, True])
def test_explicit_embedding_preserves_transcription_and_uses_current_settings(monkeypatch, queue_fails):
    from contextlib import contextmanager
    from json import dumps
    from .InternalBotService import InternalBotService

    service = object.__new__(CardAttachmentService)
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2, project_id=1, is_linked_resource=False)
    attachment = SimpleNamespace(card_id=2, deleted_at=None, get_uid=lambda: "attachment")
    document = {
        "status": "indexed",
        "generation": "source",
        "content_hash": "hash",
        "content": {"markdown": "preserved"},
        "embedding_config": {"binding_uid": "prior-binding", "model_name": "prior-model"},
        "embedding": {"status": "indexed", "pointer": {"generation": "prior"}},
    }
    metadata = Mock()
    metadata.get_document_by_attachment_uid.return_value = document
    metadata.publish_document_embedding.return_value = True
    provider = Mock()
    provider.get_document_embedding_binding.return_value = SimpleNamespace(
        get_uid=lambda: "binding",
        value=dumps(
            {
                "agent_llm": "OpenAI Compatible",
                "base_url": "https://fixture.invalid/v1",
                "api_key": "private",
                "model_name": "embed",
                "retrieval": {"enabled": False},
            }
        ),
    )
    monkeypatch.setattr(service, "_get_service", lambda cls: provider if cls is InternalBotService else metadata)
    monkeypatch.setattr(
        module.InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, card, attachment)
    )
    send = Mock(side_effect=RuntimeError("private broker address") if queue_fails else None)
    monkeypatch.setattr(module.Broker.celery, "send_task", send)

    @contextmanager
    def transaction():
        yield SimpleNamespace(after_commit=lambda callback: callback())

    monkeypatch.setattr(module.DbSession, "atomic", transaction)
    user = User(firstname="Test", lastname="Reader", email="reader@example.invalid", password="test-only")
    assert service.request_document_embedding(project, card, attachment, user=user) == "pending"
    publication = metadata.publish_document_embedding.call_args_list[0]
    assert publication.args[-1]["pointer"] == document["embedding"]["pointer"]
    assert publication.args[-1]["config"] == document["embedding_config"]
    assert publication.kwargs["expected_embedding"] == document["embedding"]
    assert "private" not in str(publication.kwargs["embedding_config"])
    assert publication.kwargs["embedding_config"]["model_name"] == "embed"
    send.assert_called_once()
    if queue_fails:
        failure = metadata.publish_document_embedding.call_args
        assert failure.args[-1]["status"] == "failed"
        assert failure.args[-1]["pointer"] == document["embedding"]["pointer"]
        assert failure.args[-1]["config"] == document["embedding_config"]
        assert "private broker address" not in failure.args[-1]["error"]
        assert failure.kwargs["expected_embedding"] == publication.args[-1]
    metadata.queue_document.assert_not_called()
    assert document["content"]["markdown"] == "preserved"
    attachment.deleted_at = "deleted"
    send.reset_mock()
    assert service.request_document_embedding(project, card, attachment, user=user) is None
    send.assert_not_called()


def test_attachment_delete_dispatches_recorded_vector_cleanup_only_after_commit(monkeypatch):
    from contextlib import contextmanager

    service = object.__new__(CardAttachmentService)
    project, card = object(), object()
    attachment = SimpleNamespace(get_uid=lambda: "attachment", order=0)
    pointer = {"generation": "recorded", "embedding_fingerprint": "a" * 64}
    metadata = Mock()
    metadata.delete_document_by_attachment_uid.return_value = {"embedding": {"pointer": pointer}}
    monkeypatch.setattr(service, "_get_service", lambda *_: metadata)
    monkeypatch.setattr(
        module.InfraHelper, "get_records_with_foreign_by_params", lambda *_: (project, card, attachment)
    )
    callbacks = []
    repository = SimpleNamespace(card_attachment=Mock())
    monkeypatch.setattr(service, "repo", repository, raising=False)

    @contextmanager
    def transaction():
        yield SimpleNamespace(after_commit=callbacks.append)

    monkeypatch.setattr(module.DbSession, "atomic", transaction)
    send = Mock()
    monkeypatch.setattr(module.Broker.celery, "send_task", send)
    monkeypatch.setattr(module.CardAttachmentPublisher, "deleted", Mock())
    monkeypatch.setattr(service, "_mark_card_changed_for_unread", Mock())
    monkeypatch.setattr(module.CardAttachmentActivityTask, "card_attachment_deleted", Mock())
    monkeypatch.setattr(module.CardAttachmentBotTask, "card_attachment_deleted", Mock())
    user = User(firstname="Test", lastname="Reader", email="reader@example.invalid", password="test-only")
    assert service.delete(user, project, card, attachment)
    send.assert_not_called()
    repository.card_attachment.delete.assert_called_once_with(attachment)
    assert len(callbacks) == 1
    callbacks[0]()
    assert send.call_args.args[0].endswith(".remove_attachment_embedding")
    # TaskParameters supplies the encoded transport; never provider credentials.
    assert "recorded" in str(send.call_args)
    assert metadata.delete_document_by_attachment_uid.call_args.args[-1] == "attachment"
