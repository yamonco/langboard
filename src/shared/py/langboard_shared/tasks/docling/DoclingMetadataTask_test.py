"""Absent optional conversion support must fail clearly before file IO."""

from types import SimpleNamespace
from unittest.mock import Mock
from langboard_shared.domain.models import CardMetadata
from langboard_shared.tasks.docling import DoclingMetadataTask as task


def test_missing_worker_package_preserves_attachment_and_skips_file_work(monkeypatch):
    attachment = SimpleNamespace(get_uid=lambda: "attachment", card_id=1, filename="report.pdf")
    card = SimpleNamespace(project_id=2)
    metadata = Mock()
    service = SimpleNamespace(
        card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment),
        card=SimpleNamespace(get_by_id_like=lambda _: card),
        project=SimpleNamespace(get_by_id_like=lambda _: object()),
        docling_metadata=metadata,
    )
    monkeypatch.setattr(task, "find_spec", lambda _: None)
    download = Mock(side_effect=AssertionError("Missing package must not download"))
    convert = Mock(side_effect=AssertionError("Missing package must not spawn conversion"))
    monkeypatch.setattr(task.Storage, "download_file", download)
    monkeypatch.setattr(task, "_convert_to_markdown", convert)

    task._index_card_attachment(service, attachment)

    download.assert_not_called()
    convert.assert_not_called()
    metadata.mark_document_indexed.assert_not_called()
    metadata.mark_document_failed.assert_called_once_with(
        CardMetadata,
        card,
        "attachment",
        "report.pdf",
        "RuntimeError: Document processing unavailable: install the document-processing extra in the broker worker.",
    )
    metadata.publish_update.assert_called_once()
