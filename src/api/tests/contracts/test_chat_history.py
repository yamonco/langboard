import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.chat_history import (  # noqa: E402
    ChatDeltaError,
    ChatMessageType,
    ChatSessionState,
    HistoryDelta,
    HistoryMessage,
    append_messages,
    apply_delta,
    extract_delta,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 7, 0, 0, tzinfo=UTC)


def message(msg_id: str, minutes: float = 0.0, **overrides) -> HistoryMessage:
    defaults = dict(
        msg_id=msg_id,
        sender="user-1",
        content=f"content-{msg_id}",
        timestamp=BASE + timedelta(minutes=minutes),
    )
    defaults.update(overrides)
    return HistoryMessage(**defaults)


class TestHistoryMessage:
    def test_requires_timezone_aware_timestamp(self):
        with pytest.raises(ValueError):
            message("1", timestamp=datetime(2026, 9, 19))

    def test_rejects_self_parent(self):
        with pytest.raises(ValueError):
            message("1", parent_id="1")

    def test_payload_round_trip(self):
        original = message("1", msg_type=ChatMessageType.CARD_ACTION, action_type="move", from_ref="todo", to_ref="doing")
        restored = HistoryMessage.from_payload(original.to_payload())
        assert restored == original
        assert restored.msg_type is ChatMessageType.CARD_ACTION


class TestAppendMessages:
    def test_appends_in_time_order(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        state = append_messages(state, (message("2", minutes=2), message("1", minutes=1)))
        assert [m.msg_id for m in state.messages] == ["1", "2"]

    def test_rejects_duplicate_ids(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        state = append_messages(state, (message("1"),))
        with pytest.raises(ChatDeltaError):
            append_messages(state, (message("1", minutes=5),))

    def test_rejects_dangling_parent(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        with pytest.raises(ChatDeltaError):
            append_messages(state, (message("1", parent_id="missing"),))

    def test_accepts_parent_within_batch(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        state = append_messages(state, (message("1", minutes=1), message("2", minutes=2, parent_id="1")))
        assert state.messages[1].parent_id == "1"


class TestApplyDelta:
    def test_new_edited_deleted(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        state = append_messages(state, (message("1", minutes=1), message("2", minutes=2), message("3", minutes=3)))
        delta = HistoryDelta(
            new=(message("4", minutes=4),),
            edited=(message("2", minutes=2, content="edited"),),
            deleted=("3",),
        )
        state = apply_delta(state, delta)
        ids = {m.msg_id: m for m in state.messages}
        assert set(ids) == {"1", "2", "4"}
        assert ids["2"].content == "edited"
        assert "3" in state.deleted_msg_ids
        assert state.last_synced_at is not None and state.last_synced_at >= BASE

    def test_unknown_edited_raises_for_fallback(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        with pytest.raises(ChatDeltaError):
            apply_delta(state, HistoryDelta(edited=(message("ghost"),)))

    def test_unknown_delete_raises(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        with pytest.raises(ChatDeltaError):
            apply_delta(state, HistoryDelta(deleted=("ghost",)))

    def test_empty_delta_is_noop(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        assert apply_delta(state, HistoryDelta()) is state


class TestSessionStatePayload:
    def test_round_trip(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1", title="session")
        state = append_messages(state, (message("1"),))
        restored = ChatSessionState.from_payload(state.to_payload())
        assert restored == state

    def test_restore_rejects_unordered_messages(self):
        payload = {
            "session_uid": "s1",
            "user_uid": "u1",
            "messages": [message("2", minutes=2).to_payload(), message("1", minutes=1).to_payload()],
        }
        with pytest.raises(ValueError):
            ChatSessionState.from_payload(payload)


class TestExtractDelta:
    def test_only_messages_after_since(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        state = append_messages(state, (message("1", minutes=1), message("2", minutes=2), message("3", minutes=3)))
        delta = extract_delta(state, since=BASE + timedelta(minutes=1, seconds=30))
        assert [m.msg_id for m in delta.new] == ["2", "3"]

    def test_requires_timezone_aware_since(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1")
        with pytest.raises(ValueError):
            extract_delta(state, since=datetime(2026, 9, 19))

    def test_deleted_ids_survive_as_delta(self):
        state = ChatSessionState(session_uid="s1", user_uid="u1", deleted_msg_ids=frozenset({"gone"}))
        delta = extract_delta(state, since=BASE)
        assert "gone" in delta.deleted
