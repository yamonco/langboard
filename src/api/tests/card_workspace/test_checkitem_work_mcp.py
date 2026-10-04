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


@pytest.mark.parametrize("checked_succeeds", [True, False])
def test_complete_rolls_back_stop_when_checked_save_fails(monkeypatch, checked_succeeds):
    from langboard_shared.core.db import DbSession
    from langboard_shared.core.db.DbEngine import DbEngine
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE work (status TEXT, checked INTEGER, seconds INTEGER)"))
        c.execute(text("INSERT INTO work VALUES ('stopped', 0, 0)"))
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_: (object(), SimpleNamespace(id=7)))
    item = SimpleNamespace(
        checklist_id=3, cardified_id=None, user_id=1, status=CheckitemStatus.Stopped,
        is_checked=False, get_uid=lambda: "item"
    )
    emitted = Mock()

    def stop(*_, **__):
        with DbSession.use(readonly=False) as db:
            db.exec(text("UPDATE work SET status='stopped', seconds=5"))
            db.after_commit(emitted)
        return True

    def checked(*_, **__):
        with DbSession.use(readonly=False) as db:
            db.exec(text("UPDATE work SET checked=1"))
        item.is_checked = checked_succeeds
        return checked_succeeds

    service = SimpleNamespace(
        checkitem=SimpleNamespace(get_by_id_like=lambda _: item, change_status=stop, toggle_checked=checked),
        checklist=SimpleNamespace(get_by_id_like=lambda _: SimpleNamespace(card_id=7)),
    )
    if checked_succeeds:
        assert CardMcp.change_card_checkitem_work("project", "card", "item", "complete", SimpleNamespace(id=1, get_uid=lambda: "user"), service)["is_checked"]
    else:
        with pytest.raises(ValueError, match="could not be completed"):
            CardMcp.change_card_checkitem_work("project", "card", "item", "complete", SimpleNamespace(id=1), service)
    with engine.connect() as c:
        assert c.execute(text("SELECT checked,seconds FROM work")).one() == ((1, 5) if checked_succeeds else (0, 0))
    assert emitted.call_count == int(checked_succeeds)
    engine.dispose()
