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
    monkeypatch.setattr(
        BoardCardApi.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *_args: (object(), card),
    )
    monkeypatch.setattr(BoardCardApi, "NativeCardWorkspaceAdapter", lambda *_args: object())
    bundle = Mock(
        return_value=SimpleNamespace(
            model_dump=lambda **_kwargs: {"card": {"core": {"uid": "card", "updated_at": revision.isoformat()}}}
        )
    )
    fence = Mock(return_value=SimpleNamespace(revision=revision, is_ready=True, generation=5))
    monkeypatch.setattr(BoardCardApi, "get_card_bundle", bundle)
    monkeypatch.setattr(BoardCardApi, "current_execution", fence)
    monkeypatch.setattr(BoardCardApi, "receipt_history", lambda _card_id: [])

    response = BoardCardApi.get_card_context("project", "card", object(), object())
    assert json.loads(response.body)["scope_context"]["card"]["execution"] == {
        "is_ready": True,
        "generation": 5,
    }
    assert bundle.call_count == 1
    fence.assert_called_once_with(42)

    fence.return_value.revision = revision + timedelta(seconds=1)
    with pytest.raises(ApiException.Conflict_409) as conflict:
        BoardCardApi.get_card_context("project", "card", object(), object())
    assert conflict.value.status_code == 409
