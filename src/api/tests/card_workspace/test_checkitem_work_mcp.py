import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.mcp_tools import CardMcp  # noqa: E402
from langboard_shared.domain.models.Checkitem import CheckitemStatus  # noqa: E402


def test_work_rejects_checkitem_from_another_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_: (object(), SimpleNamespace(id=7)))
    item = SimpleNamespace(checklist_id=3, cardified_id=None)
    change = Mock()
    service = SimpleNamespace(
        checkitem=SimpleNamespace(get_by_id_like=lambda _: item, change_status=change),
        checklist=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(card_id=8)),
    )

    with pytest.raises(ValueError, match="not found in card"):
        CardMcp.change_card_checkitem_work("project", "card", "item", "start", object(), service)
    change.assert_not_called()


def test_work_start_requires_explicit_active_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_: (object(), SimpleNamespace(id=7)))
    item = SimpleNamespace(
        checklist_id=3, cardified_id=None, user_id=None, status=CheckitemStatus.Stopped, get_uid=lambda: "item"
    )
    change = Mock()
    service = SimpleNamespace(
        checkitem=SimpleNamespace(
            get_by_id_like=lambda _: item,
            get_active_work=lambda _: [{"checkitem": {"uid": "other"}}],
            change_status=change,
        ),
        checklist=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(card_id=7)),
    )

    with pytest.raises(ValueError, match="replace_active"):
        CardMcp.change_card_checkitem_work(
            "project", "card", "item", "start", SimpleNamespace(id=1), service
        )
    change.assert_not_called()
