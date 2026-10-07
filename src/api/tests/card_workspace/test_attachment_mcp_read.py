import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import CardMcp  # noqa: E402


def test_attachment_read_checks_card_ancestry_before_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(card_id=8, deleted_at=None)
    read_bytes = Mock(return_value=b"secret")
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp.Storage, "get_file", read_bytes)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=Mock(return_value=(object(), card, object()))), card_attachment=SimpleNamespace(get_by_id_like=lambda _, **kwargs: attachment))

    with pytest.raises(ValueError, match="not found in card"):
        CardMcp.read_card_attachment("project", "card", "foreign", object(), service)
    read_bytes.assert_not_called()


def test_attachment_read_returns_bounded_file_object(monkeypatch: pytest.MonkeyPatch) -> None:
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(
        card_id=7, deleted_at=None, filename="report.pdf", file=object(), get_uid=lambda: "attachment"
    )
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp.Storage, "get_file", lambda _: b"%PDF")
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=Mock(return_value=(object(), card, object()))), card_attachment=SimpleNamespace(get_by_id_like=lambda _, **kwargs: attachment))

    result = CardMcp.read_card_attachment("project", "card", "attachment", object(), service)
    assert result == {
        "attachment_uid": "attachment",
        "file_name": "report.pdf",
        "mime_type": "application/pdf",
        "size": 4,
        "file_data_base64": "JVBERg==",
    }


@pytest.mark.parametrize("changed", ["already_deleted", "deleted", "replaced", "renamed", "removed", "foreign"])
def test_deleted_attachment_never_returns_bytes(monkeypatch, changed):
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(
        card_id=7,
        deleted_at="deleted" if changed == "already_deleted" else None,
        filename="report.pdf",
        file=object(),
        get_uid=lambda: "attachment",
    )
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (object(), card))

    def read(_):
        if changed == "deleted":
            attachment.deleted_at = "deleted"
        elif changed == "replaced":
            attachment.file = object()
        elif changed == "renamed":
            attachment.filename = "other.pdf"
        elif changed == "foreign":
            attachment.card_id = 9
        elif changed == "removed":
            service.card_attachment.get_by_id_like = lambda _, **kwargs: None
        return b"private"

    read_bytes = Mock(side_effect=read)
    monkeypatch.setattr(CardMcp.Storage, "get_file", read_bytes)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=Mock(return_value=(object(), card, object()))), card_attachment=SimpleNamespace(get_by_id_like=lambda _, **kwargs: attachment))
    with pytest.raises(ValueError, match="unavailable|not found"):
        CardMcp.read_card_attachment("project", "card", "attachment", object(), service)
    if changed == "already_deleted":
        read_bytes.assert_not_called()


@pytest.mark.parametrize("phase", ["before", "during"])
def test_card_visibility_revocation_never_returns_attachment_bytes(monkeypatch, phase):
    card = SimpleNamespace(id=7)
    attachment = SimpleNamespace(card_id=7, deleted_at=None, filename="proof.pdf", file=object(), get_uid=lambda: "a")
    resolver = Mock(return_value=None if phase == "before" else (object(), card, object()))
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=resolver), card_attachment=SimpleNamespace(get_by_id_like=lambda _, **kwargs: attachment))
    def read(_):
        resolver.return_value = None
        return b"secret"
    reader = Mock(side_effect=read)
    monkeypatch.setattr(CardMcp.Storage, "get_file", reader)
    with pytest.raises(ValueError, match="unavailable|not found"):
        CardMcp.read_card_attachment("p", "c", "a", object(), service)
    if phase == "before":
        reader.assert_not_called()
