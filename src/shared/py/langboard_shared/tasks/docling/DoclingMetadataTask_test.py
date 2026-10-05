"""Absent optional conversion support must fail clearly before file IO."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.models import CardMetadata
from langboard_shared.tasks.docling import DoclingMetadataTask as task


def test_missing_worker_package_preserves_attachment_and_skips_file_work(monkeypatch):
    attachment = SimpleNamespace(get_uid=lambda: "attachment", card_id=1, filename="report.pdf", file=object())
    card = SimpleNamespace(project_id=2)
    metadata = Mock()
    metadata.get_document_by_attachment_uid.return_value = {
        "vision_config": {"binding_uid": "vision", "model_name": "upload-model", "base_url": "https://example.test/v1"}
    }
    service = SimpleNamespace(
        internal_bot=SimpleNamespace(
            get_by_id_like=lambda _: SimpleNamespace(
                value='{"api_key":"test-key","model_name":"changed-global-model","base_url":"https://example.test/v1"}'
            )
        ),
        card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment),
        card=SimpleNamespace(get_by_id_like=lambda _: card),
        project=SimpleNamespace(get_by_id_like=lambda _: object()),
        docling_metadata=metadata,
    )
    monkeypatch.setattr(task, "find_spec", lambda _: None, raising=False)
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
        generation=None,
    )
    metadata.publish_update.assert_called_once()


def test_unrequested_attachment_never_starts_processing(monkeypatch):
    attachment = SimpleNamespace(get_uid=lambda: "attachment", card_id=1, filename="report.pdf")
    card = SimpleNamespace(project_id=2)
    metadata = Mock()
    metadata.get_document_by_attachment_uid.return_value = None
    binding = Mock(side_effect=AssertionError("Global settings must not trigger old attachments"))
    service = SimpleNamespace(
        internal_bot=SimpleNamespace(get_by_id_like=binding),
        card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment),
        card=SimpleNamespace(get_by_id_like=lambda _: card),
        project=SimpleNamespace(get_by_id_like=lambda _: object()),
        docling_metadata=metadata,
    )
    download = Mock()
    monkeypatch.setattr(task.Storage, "download_file", download)
    task._index_card_attachment(service, attachment)
    binding.assert_not_called()
    download.assert_not_called()
    metadata.claim_document.assert_not_called()
    metadata.mark_document_failed.assert_not_called()


def test_converter_process_streams_pages_and_keywords_without_exposing_stdin(monkeypatch, tmp_path):
    script = tmp_path / "converter.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "config = json.loads(sys.stdin.read())\n"
        "assert config['api_key'] == 'fixture-private-key'\n"
        "print('LANGBOARD_DOCLING_PROGRESS:not-json', flush=True)\n"
        'print(\'LANGBOARD_DOCLING_PROGRESS:{"completed_pages": 3, "total_pages": 2}\', flush=True)\n'
        'print(\'LANGBOARD_DOCLING_PROGRESS:{"completed_pages": 1, "total_pages": 2}\', flush=True)\n'
        'print(\'LANGBOARD_DOCLING_KEYWORDS:{"keywords": {"ko": ["문서"]}}\', flush=True)\n'
        'print(\'LANGBOARD_DOCLING_PROGRESS:{"completed_pages": 2, "total_pages": 2}\', flush=True)\n'
        "pathlib.Path(sys.argv[1]).write_text('faithful original', encoding='utf-8')\n",
        encoding="utf-8",
    )
    output_paths = []

    def launch(command, **kwargs):
        assert "fixture-private-key" not in " ".join(command)
        output_paths.append(command[4])
        return subprocess.Popen([sys.executable, str(script), command[4]], **kwargs)

    monkeypatch.setattr(task, "Popen", launch)
    progress, keywords = [], []
    result = task._convert_to_markdown(
        "fixture.pdf",
        lambda done, total: progress.append((done, total)),
        vision_value='{"api_key":"fixture-private-key"}',
        on_keywords=keywords.append,
    )
    assert result == "faithful original"
    assert progress == [(1, 2), (2, 2)]
    assert keywords == [{"ko": ["문서"]}]
    assert not any(task.Path(path).exists() for path in output_paths)


def test_converter_timeout_kills_process_and_removes_partial_output(monkeypatch, tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    processes, output_paths = [], []

    def launch(command, **kwargs):
        output_paths.append(command[4])
        process = subprocess.Popen([sys.executable, str(script)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(task, "Popen", launch)
    monkeypatch.setattr(task, "Env", SimpleNamespace(DOCLING_CONVERSION_TIMEOUT_SECONDS=0.1))
    with pytest.raises(subprocess.TimeoutExpired):
        task._convert_to_markdown("fixture.pdf")
    assert all(process.poll() is not None for process in processes)
    assert not any(task.Path(path).exists() for path in output_paths)


def test_upload_binding_snapshot_survives_global_model_change(monkeypatch):
    from json import loads

    attachment = SimpleNamespace(get_uid=lambda: "attachment", card_id=1, filename="report.pdf", file=object())
    card = SimpleNamespace(project_id=2)
    metadata = Mock()
    metadata.get_document_by_attachment_uid.return_value = {
        "vision_config": {"binding_uid": "vision", "model_name": "upload-model", "base_url": "https://example.test/v1"}
    }
    service = SimpleNamespace(
        internal_bot=SimpleNamespace(
            get_by_id_like=lambda _: SimpleNamespace(
                value='{"api_key":"test-key","model_name":"changed-global-model","base_url":"https://example.test/v1"}'
            )
        ),
        card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment),
        card=SimpleNamespace(get_by_id_like=lambda _: card),
        project=SimpleNamespace(get_by_id_like=lambda _: object()),
        docling_metadata=metadata,
    )
    monkeypatch.setattr(task, "find_spec", lambda _: object())

    def download(_, output):
        output.write(b"source")
        return True

    monkeypatch.setattr(task.Storage, "download_file", download)
    convert = Mock(return_value="original text")
    monkeypatch.setattr(task, "_convert_to_markdown", convert)
    task._index_card_attachment(service, attachment)
    config = loads(convert.call_args.kwargs["vision_value"])
    assert config["model_name"] == "upload-model"
    assert config["api_key"] == "test-key"
    assert "binding_uid" not in config
    metadata.mark_document_indexed.assert_called_once()
    metadata.mark_document_failed.assert_not_called()
