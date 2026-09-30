import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import CardMcp  # noqa: E402


def test_attachment_read_checks_card_ancestry_before_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(card_id=8)
    read_bytes = Mock(return_value=b"secret")
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp.Storage, "get_file", read_bytes)
    service = SimpleNamespace(card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment))

    with pytest.raises(ValueError, match="not found in card"):
        CardMcp.read_card_attachment("project", "card", "foreign", object(), service)
    read_bytes.assert_not_called()


def test_attachment_read_returns_bounded_file_object(monkeypatch: pytest.MonkeyPatch) -> None:
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(card_id=7, filename="report.pdf", file=object(), get_uid=lambda: "attachment")
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp.Storage, "get_file", lambda _: b"%PDF")
    service = SimpleNamespace(card_attachment=SimpleNamespace(get_by_id_like=lambda _: attachment))

    result = CardMcp.read_card_attachment("project", "card", "attachment", object(), service)
    assert result == {
        "attachment_uid": "attachment",
        "file_name": "report.pdf",
        "mime_type": "application/pdf",
        "size": 4,
        "file_data_base64": "JVBERg==",
    }
