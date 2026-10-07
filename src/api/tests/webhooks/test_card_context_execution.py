"""The card context carries the current execution fence in its one response."""

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.board import BoardCardApi  # noqa: E402
from langboard_shared.core.routing import ApiException  # noqa: E402


def test_card_context_includes_ready_generation_and_rejects_mixed_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = datetime(2026, 9, 25, tzinfo=timezone.utc)
    card = SimpleNamespace(id=42)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=lambda *args: (object(), card, object())))
    request = SimpleNamespace(scope={})
    monkeypatch.setattr(BoardCardApi, "NativeCardWorkspaceAdapter", lambda *_args, **_kwargs: object())
    bundle = Mock(
        return_value=SimpleNamespace(
            model_dump=lambda **_kwargs: {"card": {"core": {"uid": "card", "updated_at": revision.isoformat()}}}
        )
    )
    fence = Mock(return_value=SimpleNamespace(revision=revision, is_ready=True, generation=5))
    monkeypatch.setattr(BoardCardApi, "get_card_bundle", bundle)
    monkeypatch.setattr(BoardCardApi, "current_execution", fence)
    monkeypatch.setattr(BoardCardApi, "receipt_history", lambda _card_id: [])

    response = BoardCardApi.get_card_context("project", "card", object(), service, request=request)
    assert json.loads(response.body)["scope_context"]["card"]["execution"] == {
        "is_ready": True,
        "generation": 5,
    }
    assert bundle.call_count == 1
    fence.assert_called_once_with(42)

    fence.return_value.revision = revision + timedelta(seconds=1)
    with pytest.raises(ApiException.Conflict_409) as conflict:
        BoardCardApi.get_card_context("project", "card", object(), service, request=request)
    assert conflict.value.status_code == 409


def test_unreadable_details_context_and_comments_return_not_found_before_sections(monkeypatch):
    card_service = SimpleNamespace(resolve_readable_card=Mock(return_value=None), get_details=Mock())
    service = SimpleNamespace(card=card_service, card_comment=SimpleNamespace(get_api_list_by_card=Mock()))
    request = SimpleNamespace(scope={})
    bundle = Mock()
    monkeypatch.setattr(BoardCardApi, "get_card_bundle", bundle)
    for callback in (
        lambda: BoardCardApi.get_card_details("p", "c", request, object(), service),
        lambda: BoardCardApi.get_card_context("p", "c", object(), service, request=request),
        lambda: BoardCardApi.get_card_comments("p", "c", request, object(), service),
    ):
        with pytest.raises(ApiException.NotFound_404):
            callback()
    card_service.get_details.assert_not_called()
    service.card_comment.get_api_list_by_card.assert_not_called()
    bundle.assert_not_called()
