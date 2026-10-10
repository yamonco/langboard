import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.chat_context_window import (  # noqa: E402
    ContextWindowPolicy,
    build_context_window,
    enforce_char_budget,
    estimate_context_chars,
    fallback_full_resend,
)
from langboard_shared.domain.contracts.chat_history import ChatMessageType, HistoryMessage  # noqa: E402


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 8, 0, 0, tzinfo=UTC)


def message(msg_id: str, minutes: float, content: str | None = None) -> HistoryMessage:
    return HistoryMessage(
        msg_id=msg_id,
        sender="user-1",
        content=content if content is not None else f"content-{msg_id}",
        timestamp=BASE + timedelta(minutes=minutes),
    )


def summarize(overflow):
    return f"{len(overflow)} earlier messages"


class TestBuildContextWindow:
    def test_keeps_everything_under_limit(self):
        messages = [message("1", 1), message("2", 2)]
        result = build_context_window(messages, ContextWindowPolicy(max_messages=5))
        assert [m.msg_id for m in result] == ["1", "2"]

    def test_trims_to_newest_without_summarizer(self):
        messages = [message(str(i), i) for i in range(1, 6)]
        result = build_context_window(messages, ContextWindowPolicy(max_messages=2, summarize_overflow=True))
        assert [m.msg_id for m in result] == ["4", "5"]

    def test_prepends_summary_message_with_summarizer(self):
        messages = [message(str(i), i) for i in range(1, 6)]
        result = build_context_window(messages, ContextWindowPolicy(max_messages=2), summarizer=summarize)
        assert [m.msg_type for m in result] == [ChatMessageType.SUMMARY, ChatMessageType.CHAT, ChatMessageType.CHAT]
        assert result[0].sender == "system"
        assert "3 earlier messages" in result[0].content
        assert result[1].msg_id == "4"

    def test_rejects_invalid_window(self):
        with pytest.raises(ValueError):
            build_context_window([], ContextWindowPolicy(max_messages=0))

    def test_orders_unsorted_input(self):
        result = build_context_window([message("3", 3), message("1", 1)], ContextWindowPolicy(max_messages=5))
        assert [m.msg_id for m in result] == ["1", "3"]


class TestCharBudget:
    def test_estimate_is_positive_per_message(self):
        assert estimate_context_chars([message("1", 1, "abc")]) == len("abc") + 96

    def test_drops_oldest_until_budget(self):
        messages = [message(str(i), i, content="x" * 500) for i in range(1, 5)]
        result = enforce_char_budget(messages, max_chars=3 * (500 + 96))
        assert [m.msg_id for m in result] == ["2", "3", "4"]

    def test_summarizes_dropped_prefix(self):
        messages = [message(str(i), i, content="x" * 500) for i in range(1, 5)]
        result = enforce_char_budget(messages, max_chars=3 * (500 + 96), summarizer=summarize)
        assert result[0].msg_type is ChatMessageType.SUMMARY
        assert "1 earlier messages" in result[0].content

    def test_rejects_nonpositive_budget(self):
        with pytest.raises(ValueError):
            enforce_char_budget([], max_chars=0)


class TestFallbackFullResend:
    def test_full_resend_rebuilds_window(self):
        messages = [message(str(i), i) for i in range(1, 6)]
        result = fallback_full_resend(messages, ContextWindowPolicy(max_messages=2))
        assert [m.msg_id for m in result] == ["4", "5"]
