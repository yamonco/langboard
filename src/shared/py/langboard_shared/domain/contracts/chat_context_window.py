"""Context window policy for hybrid chat history compression.

Keeps the newest messages inside a bounded window and replaces the
overflow with an optional summary message, producing the exact message
list an agent receives. Framework-free; the summary itself is supplied
by the caller (LLM) so the policy stays deterministic and testable.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence
from .chat_history import ChatMessageType, HistoryMessage


@dataclass(frozen=True)
class ContextWindowPolicy:
    """Bounds and summary behavior for agent context assembly."""

    max_messages: int = 50
    max_content_chars: int | None = None
    summarize_overflow: bool = True


SUMMARY_SENDER = "system"
SUMMARY_PREFIX = "summary of earlier conversation"

OverflowSummarizer = Callable[[tuple[HistoryMessage, ...]], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_context_window(
    messages: Sequence[HistoryMessage],
    policy: ContextWindowPolicy | None = None,
    summarizer: OverflowSummarizer | None = None,
    now: datetime | None = None,
) -> tuple[HistoryMessage, ...]:
    """Return the messages an agent should see under the window policy.

    The newest ``max_messages`` messages are always kept verbatim. When
    older messages overflow and ``summarize_overflow`` is set, a summary
    message (msg_type=summary) is prepended; without a summarizer the
    overflow is dropped. Window bounds below one are rejected.
    """

    if policy is None:
        policy = ContextWindowPolicy()
    if policy.max_messages < 1:
        raise ValueError("max_messages must be at least 1")

    ordered = sorted(messages, key=lambda message: (message.timestamp, message.msg_id))
    if len(ordered) <= policy.max_messages:
        return tuple(ordered)

    kept = ordered[-policy.max_messages :]
    if not policy.summarize_overflow or summarizer is None:
        return tuple(kept)

    overflow = tuple(ordered[: -policy.max_messages])
    summary = HistoryMessage(
        msg_id=f"summary:{kept[0].msg_id}",
        sender=SUMMARY_SENDER,
        content=f"{SUMMARY_PREFIX}: {summarizer(overflow)}",
        timestamp=(now or _utc_now()),
        msg_type=ChatMessageType.SUMMARY,
    )
    return (summary, *kept)


def estimate_context_chars(messages: Sequence[HistoryMessage]) -> int:
    """Approximate serialized size of the context payload."""

    return sum(len(message.content) + 96 for message in messages)


def enforce_char_budget(
    messages: Sequence[HistoryMessage],
    max_chars: int,
    summarizer: OverflowSummarizer | None = None,
) -> tuple[HistoryMessage, ...]:
    """Drop or summarize oldest messages until the char budget holds.

    Kept messages are contiguous from the newest side so replies stay
    anchored to recent turns. A summary is prepended only when a
    summarizer is provided.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    ordered = sorted(messages, key=lambda message: (message.timestamp, message.msg_id))
    kept = list(ordered)
    while kept and estimate_context_chars(kept) > max_chars:
        kept.pop(0)

    dropped = ordered[: len(ordered) - len(kept)]
    if dropped and summarizer is not None:
        summary = HistoryMessage(
            msg_id=f"summary:{kept[0].msg_id}" if kept else "summary:empty",
            sender=SUMMARY_SENDER,
            content=f"{SUMMARY_PREFIX}: {summarizer(tuple(dropped))}",
            timestamp=kept[0].timestamp if kept else _utc_now(),
            msg_type=ChatMessageType.SUMMARY,
        )
        return (summary, *kept)
    return tuple(kept)


def fallback_full_resend(messages: Sequence[HistoryMessage], policy: ContextWindowPolicy | None = None) -> tuple[HistoryMessage, ...]:
    """Recovery path after a failed delta apply: the full window again."""

    return build_context_window(messages, policy, summarizer=None)
