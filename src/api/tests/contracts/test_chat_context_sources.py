import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.chat_context_sources import (  # noqa: E402
    CardContextRecord,
    WikiContextRecord,
    card_action_message,
    card_comment_message,
    context_anchor_ids,
    inject_card_context,
    inject_wiki_context,
    wiki_edit_message,
)
from langboard_shared.domain.contracts.chat_history import ChatMessageType, HistoryMessage  # noqa: E402


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 9, 0, 0, tzinfo=UTC)


def chat(msg_id: str, minutes: float) -> HistoryMessage:
    return HistoryMessage(
        msg_id=msg_id,
        sender="user-1",
        content=f"chat-{msg_id}",
        timestamp=BASE + timedelta(minutes=minutes),
    )


class TestCardActionMessage:
    def test_normalizes_action(self):
        record = CardContextRecord(
            uid="ev1",
            card_uid="card-1",
            actor="user-2",
            created_at=BASE,
            action_type="move",
            from_ref="todo",
            to_ref="doing",
        )
        message = card_action_message(record)
        assert message.msg_id == "card:ev1"
        assert message.msg_type is ChatMessageType.CARD_ACTION
        assert (message.action_type, message.from_ref, message.to_ref) == ("move", "todo", "doing")

    def test_rejects_naive_timestamp(self):
        record = CardContextRecord(
            uid="ev1",
            card_uid="card-1",
            actor="user-2",
            created_at=datetime(2026, 9, 19),
            action_type="move",
        )
        with pytest.raises(ValueError):
            card_action_message(record)

    def test_rejects_missing_card(self):
        record = CardContextRecord(uid="ev1", card_uid="", actor="u", created_at=BASE, action_type="move")
        with pytest.raises(ValueError):
            card_action_message(record)


class TestCardCommentMessage:
    def test_threads_under_card_anchor(self):
        message = card_comment_message(uid="c1", card_uid="card-1", author="user-2", created_at=BASE, content="이거 언제 끝나요?")
        assert message.msg_type is ChatMessageType.COMMENT
        assert message.parent_id == "card-anchor:card-1"

    def test_rejects_empty_content(self):
        with pytest.raises(ValueError):
            card_comment_message(uid="c1", card_uid="card-1", author="u", created_at=BASE, content="   ")


class TestWikiContext:
    def test_normalizes_edit(self):
        message = wiki_edit_message(WikiContextRecord(uid="w1", wiki_uid="wiki-1", actor="user-3", created_at=BASE, title="Runbook"))
        assert message.msg_type is ChatMessageType.SYSTEM_NOTICE
        assert "Runbook" in message.content


class TestInjectCardContext:
    def test_merges_and_orders(self):
        card_records = [
            CardContextRecord(uid="ev2", card_uid="card-1", actor="u2", created_at=BASE + timedelta(minutes=3), action_type="move"),
            CardContextRecord(uid="ev1", card_uid="card-1", actor="u2", created_at=BASE + timedelta(minutes=1), action_type="create"),
        ]
        comments = [
            {"uid": "c1", "card_uid": "card-1", "author": "u3", "created_at": BASE + timedelta(minutes=2), "content": "comment"},
        ]
        merged = inject_card_context([chat("m1", 0), chat("m2", 4)], card_records, comments)
        assert [m.msg_id for m in merged] == ["m1", "card:ev1", "comment:c1", "card:ev2", "m2"]

    def test_anchor_ids_collect_card_anchors(self):
        comments = [
            {"uid": "c1", "card_uid": "card-9", "author": "u3", "created_at": BASE, "content": "x"},
        ]
        merged = inject_card_context([], [], comments)
        assert "card-anchor:card-9" in context_anchor_ids(merged)


class TestInjectWikiContext:
    def test_merges_and_orders(self):
        wiki_records = [WikiContextRecord(uid="w1", wiki_uid="wiki-1", actor="u", created_at=BASE + timedelta(minutes=2), title="Guide")]
        merged = inject_wiki_context([chat("m1", 0), chat("m2", 5)], wiki_records)
        assert [m.msg_id for m in merged] == ["m1", "wiki:w1", "m2"]
