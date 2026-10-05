"""Historical imports must not consume current automatic VLM settings."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock
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
