"""Card and wiki context injection into the hybrid chat history.

Converts board records (card actions, comments, wiki edits) into the
shared HistoryMessage ontology and merges them with chat messages so
an agent sees one time-ordered hybrid history. Pure functions over
plain payloads — no model imports.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence
from .chat_history import ChatMessageType, HistoryMessage


@dataclass(frozen=True)
class CardContextRecord:
    """A board event worth surfacing in a chat context."""

    uid: str
    card_uid: str
    actor: str
    created_at: datetime
    action_type: str
    from_ref: str | None = None
    to_ref: str | None = None
    content: str = ""


@dataclass(frozen=True)
class WikiContextRecord:
    """A wiki change worth surfacing in a chat context."""

    uid: str
    wiki_uid: str
    actor: str
    created_at: datetime
    title: str


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def card_action_message(record: CardContextRecord) -> HistoryMessage:
    """Normalize one card event into a card_action HistoryMessage."""

    _require_timezone(record.created_at, "created_at")
    if not record.card_uid:
        raise ValueError("card_uid is required")
    return HistoryMessage(
        msg_id=f"card:{record.uid}",
        sender=record.actor,
        content=record.content or f"{record.action_type} {record.card_uid}",
        timestamp=record.created_at,
        msg_type=ChatMessageType.CARD_ACTION,
        parent_id=None,
        action_type=record.action_type,
        from_ref=record.from_ref,
        to_ref=record.to_ref,
    )


def card_comment_message(*, uid: str, card_uid: str, author: str, created_at: datetime, content: str) -> HistoryMessage:
    """Normalize one card comment into a threaded comment HistoryMessage."""

    _require_timezone(created_at, "created_at")
    if not content.strip():
        raise ValueError("comment content cannot be empty")
    return HistoryMessage(
        msg_id=f"comment:{uid}",
        sender=author,
        content=content,
        timestamp=created_at,
        msg_type=ChatMessageType.COMMENT,
        parent_id=f"card-anchor:{card_uid}",
        action_type=None,
    )


def wiki_edit_message(record: WikiContextRecord) -> HistoryMessage:
    """Normalize one wiki change into a system-notice HistoryMessage."""

    _require_timezone(record.created_at, "created_at")
    return HistoryMessage(
        msg_id=f"wiki:{record.uid}",
        sender=record.actor,
        content=f"wiki '{record.title}' updated",
        timestamp=record.created_at,
        msg_type=ChatMessageType.SYSTEM_NOTICE,
    )


def inject_card_context(
    chat_messages: Sequence[HistoryMessage],
    card_records: Iterable[CardContextRecord],
    comment_records: Iterable[dict[str, Any]] = (),
) -> tuple[HistoryMessage, ...]:
    """Merge card actions and comments into one ordered hybrid history.

    Comment messages keep their card anchor as parent_id so consumers
    can rebuild threads; anchors are not materialized as messages.
    """

    merged = list(chat_messages)
    merged.extend(card_action_message(record) for record in card_records)
    merged.extend(
        card_comment_message(
            uid=item["uid"],
            card_uid=item["card_uid"],
            author=item["author"],
            created_at=item["created_at"],
            content=item["content"],
        )
        for item in comment_records
    )
    return tuple(sorted(merged, key=lambda message: (message.timestamp, message.msg_id)))


def inject_wiki_context(chat_messages: Sequence[HistoryMessage], wiki_records: Iterable[WikiContextRecord]) -> tuple[HistoryMessage, ...]:
    """Merge wiki edits into one ordered hybrid history."""

    merged = list(chat_messages)
    merged.extend(wiki_edit_message(record) for record in wiki_records)
    return tuple(sorted(merged, key=lambda message: (message.timestamp, message.msg_id)))


def context_anchor_ids(messages: Sequence[HistoryMessage]) -> frozenset[str]:
    """Collect distinct card/wiki anchors referenced by injected messages."""

    anchors: set[str] = set()
    for message in messages:
        if message.msg_type is ChatMessageType.CARD_ACTION and message.content and message.to_ref:
            anchors.add(f"card-anchor:{message.to_ref}")
        if message.parent_id and message.parent_id.startswith("card-anchor:"):
            anchors.add(message.parent_id)
    return frozenset(anchors)
