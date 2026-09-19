"""Hybrid chat/card history ontology and session persistence rules.

Every history-bearing record (chat message, card comment, card action,
summary, system notice) is normalized into one Message structure so an
agent context can be assembled, synchronized by delta, and restored
from durable storage without framework dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ChatMessageType(str, Enum):
    """Message ontology shared by chat, comments, and card events."""

    CHAT = "chat"
    COMMENT = "comment"
    CARD_ACTION = "card_action"
    SUMMARY = "summary"
    SYSTEM_NOTICE = "system_notice"
    FILE_UPLOAD = "file_upload"


class ChatDeltaError(ValueError):
    """Raised when a delta cannot be applied; callers fall back to a full window resend."""


@dataclass(frozen=True)
class HistoryMessage:
    """One normalized history record regardless of its origin."""

    msg_id: str
    sender: str
    content: str
    timestamp: datetime
    msg_type: ChatMessageType = ChatMessageType.CHAT
    parent_id: str | None = None
    action_type: str | None = None
    from_ref: str | None = None
    to_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.msg_id:
            raise ValueError("msg_id is required")
        if not self.sender:
            raise ValueError("sender is required")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.parent_id is not None and self.parent_id == self.msg_id:
            raise ValueError("parent_id cannot reference itself")

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the JSON-safe delta payload shape."""

        return {
            "msg_id": self.msg_id,
            "sender": self.sender,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "msg_type": self.msg_type.value,
            "parent_id": self.parent_id,
            "action_type": self.action_type,
            "from_ref": self.from_ref,
            "to_ref": self.to_ref,
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "HistoryMessage":
        """Restore a message from its serialized payload."""

        return HistoryMessage(
            msg_id=payload["msg_id"],
            sender=payload["sender"],
            content=payload.get("content", ""),
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            msg_type=ChatMessageType(payload.get("msg_type", ChatMessageType.CHAT.value)),
            parent_id=payload.get("parent_id"),
            action_type=payload.get("action_type"),
            from_ref=payload.get("from_ref"),
            to_ref=payload.get("to_ref"),
        )


@dataclass(frozen=True)
class HistoryDelta:
    """Changes since the last agent synchronization."""

    new: tuple[HistoryMessage, ...] = field(default_factory=tuple)
    edited: tuple[HistoryMessage, ...] = field(default_factory=tuple)
    deleted: tuple[str, ...] = field(default_factory=tuple)
    since: datetime | None = None

    def is_empty(self) -> bool:
        """Return whether there is nothing to apply."""

        return not (self.new or self.edited or self.deleted)

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the wire delta shape."""

        return {
            "type": "delta",
            "new": [message.to_payload() for message in self.new],
            "edited": [message.to_payload() for message in self.edited],
            "deleted": list(self.deleted),
            "since": self.since.isoformat() if self.since else None,
        }


@dataclass(frozen=True)
class ChatSessionState:
    """Durable projection of one chat session's normalized history."""

    session_uid: str
    user_uid: str
    title: str = ""
    messages: tuple[HistoryMessage, ...] = field(default_factory=tuple)
    deleted_msg_ids: frozenset[str] = field(default_factory=frozenset)
    last_synced_at: datetime | None = None

    def message_ids(self) -> frozenset[str]:
        """Return identifiers of every live message."""

        return frozenset(message.msg_id for message in self.messages)

    def to_payload(self) -> dict[str, Any]:
        """Serialize for persistence."""

        return {
            "session_uid": self.session_uid,
            "user_uid": self.user_uid,
            "title": self.title,
            "messages": [message.to_payload() for message in self.messages],
            "deleted_msg_ids": sorted(self.deleted_msg_ids),
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "ChatSessionState":
        """Restore a persisted session state, validating ordering."""

        state = ChatSessionState(
            session_uid=payload["session_uid"],
            user_uid=payload["user_uid"],
            title=payload.get("title", ""),
            messages=tuple(HistoryMessage.from_payload(item) for item in payload.get("messages", [])),
            deleted_msg_ids=frozenset(payload.get("deleted_msg_ids", [])),
            last_synced_at=datetime.fromisoformat(payload["last_synced_at"]) if payload.get("last_synced_at") else None,
        )
        timestamps = [message.timestamp for message in state.messages]
        if timestamps != sorted(timestamps):
            raise ValueError("persisted messages must stay time-ordered")
        return state


def _ordered(messages: tuple[HistoryMessage, ...]) -> tuple[HistoryMessage, ...]:
    return tuple(sorted(messages, key=lambda message: (message.timestamp, message.msg_id)))


def append_messages(state: ChatSessionState, messages: tuple[HistoryMessage, ...]) -> ChatSessionState:
    """Append messages immutably, rejecting duplicates and dangling parents."""

    if not messages:
        return state

    existing_ids = state.message_ids()
    incoming_ids = [message.msg_id for message in messages]
    if len(incoming_ids) != len(set(incoming_ids)):
        raise ChatDeltaError("duplicate msg_id in appended batch")
    if existing_ids & set(incoming_ids):
        raise ChatDeltaError("msg_id already exists in session")

    known_ids = existing_ids | set(incoming_ids)
    for message in messages:
        if message.parent_id is not None and message.parent_id not in known_ids:
            raise ChatDeltaError(f"parent_id {message.parent_id} not found")

    return ChatSessionState(
        session_uid=state.session_uid,
        user_uid=state.user_uid,
        title=state.title,
        messages=_ordered(state.messages + messages),
        deleted_msg_ids=state.deleted_msg_ids,
        last_synced_at=state.last_synced_at,
    )


def apply_delta(state: ChatSessionState, delta: HistoryDelta) -> ChatSessionState:
    """Apply a delta and advance last_synced_at, or raise for a full-resend fallback."""

    if delta.is_empty():
        return state

    existing = state.message_ids()
    for message in delta.new:
        if message.msg_id in existing:
            raise ChatDeltaError(f"new msg_id {message.msg_id} already exists")
    for message in delta.edited:
        if message.msg_id not in existing:
            raise ChatDeltaError(f"edited msg_id {message.msg_id} not found")
    unknown_deletes = set(delta.deleted) - existing
    if unknown_deletes:
        raise ChatDeltaError(f"deleted msg_ids unknown: {sorted(unknown_deletes)}")

    deleted = set(delta.deleted)
    edited_map = {message.msg_id: message for message in delta.edited}
    kept = []
    for message in state.messages:
        if message.msg_id in deleted:
            continue
        kept.append(edited_map.get(message.msg_id, message))

    if delta.new:
        state = append_messages(
            ChatSessionState(
                session_uid=state.session_uid,
                user_uid=state.user_uid,
                title=state.title,
                messages=tuple(kept),
                deleted_msg_ids=state.deleted_msg_ids,
                last_synced_at=state.last_synced_at,
            ),
            delta.new,
        )
    else:
        state = ChatSessionState(
            session_uid=state.session_uid,
            user_uid=state.user_uid,
            title=state.title,
            messages=_ordered(tuple(kept)),
            deleted_msg_ids=state.deleted_msg_ids,
            last_synced_at=state.last_synced_at,
        )

    return ChatSessionState(
        session_uid=state.session_uid,
        user_uid=state.user_uid,
        title=state.title,
        messages=state.messages,
        deleted_msg_ids=state.deleted_msg_ids | deleted,
        last_synced_at=_utc_now(),
    )


def extract_delta(state: ChatSessionState, since: datetime, changed: tuple[HistoryMessage, ...] = ()) -> HistoryDelta:
    """Build the delta a client needs after the given synchronization point."""

    if since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    new_messages = tuple(message for message in state.messages if message.timestamp > since)
    return HistoryDelta(
        new=new_messages,
        edited=tuple(changed),
        deleted=tuple(
            sorted(msg_id for msg_id in state.deleted_msg_ids if msg_id not in state.message_ids()),
        ),
        since=since,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
