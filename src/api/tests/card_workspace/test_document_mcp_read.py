import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")
from langboard.mcp_tools import CardMcp


def fixture(monkeypatch):
    card = SimpleNamespace(id=7, is_linked_resource=False)
    attachment = SimpleNamespace(card_id=7, deleted_at=None, filename="report.pdf")
    document = {
        "generation": "current",
        "status": "indexed",
        "content_hash": "hash",
        "content": {"markdown": "한글 日本語 中文 " * 1000},
        "embedding_config": {"api_key": "must-not-return"},
    }
    service = SimpleNamespace(
        project=SimpleNamespace(get_user_role_actions_by_project=Mock(return_value=["*"])),
        card_attachment=SimpleNamespace(get_by_id_like=Mock(return_value=attachment)),
        docling_metadata=SimpleNamespace(get_document_by_attachment_uid=Mock(return_value=document)),
    )
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    return service, card, attachment, document


@pytest.mark.parametrize("denial", ["revoked", "foreign", "deleted", "linked"])
def test_denied_or_deleted_sources_never_load_transcription(monkeypatch, denial):
    service, card, attachment, _ = fixture(monkeypatch)
    if denial == "revoked":
        service.project.get_user_role_actions_by_project.return_value = []
    if denial == "foreign":
        attachment.card_id = 99
    if denial == "deleted":
        attachment.deleted_at = "deleted"
    if denial == "linked":
        card.is_linked_resource = True
    with pytest.raises(ValueError, match="unavailable"):
        CardMcp.read_card_document("board", "card", "attachment", object(), service)
    service.docling_metadata.get_document_by_attachment_uid.assert_not_called()


def test_read_is_bounded_non_destructive_and_generation_fenced(monkeypatch):
    service, _, _, document = fixture(monkeypatch)
    result = CardMcp.read_card_document("board", "card", "attachment", object(), service, max_chars=128)
    assert result["content"] == document["content"]["markdown"][:128]
    assert result["next_offset"] == 128 and result["content_hash"] == "hash"
    assert "embedding_config" not in result
    second = CardMcp.read_card_document(
        "board",
        "card",
        "attachment",
        object(),
        service,
        offset=128,
        max_chars=128,
        expected_generation=result["generation"],
    )
    assert second["content"] == document["content"]["markdown"][128:256]
    document["generation"] = "replaced"
    with pytest.raises(ValueError, match="generation changed"):
        CardMcp.read_card_document("board", "card", "attachment", object(), service, expected_generation="current")
    assert document["content"]["markdown"] == "한글 日本語 中文 " * 1000


@pytest.mark.parametrize("offset,max_chars", [(-1, 128), (False, 128), (0, 8001), (0, False)])
def test_invalid_bounds_never_load_sources(monkeypatch, offset, max_chars):
    service, _, _, _ = fixture(monkeypatch)
    with pytest.raises(ValueError):
        CardMcp.read_card_document("board", "card", "attachment", object(), service, offset=offset, max_chars=max_chars)
    service.card_attachment.get_by_id_like.assert_not_called()


def test_pending_document_does_not_expose_stale_content(monkeypatch):
    service, _, _, document = fixture(monkeypatch)
    document["status"] = "pending"
    result = CardMcp.read_card_document("board", "card", "attachment", object(), service)
    assert result["content"] == "" and result["next_offset"] is None
