"""Idempotent consumption contract for external WorkEvent consumers.

Consumers track processed event_ids to guarantee at-most-once side effects
even when the change feed is polled with overlapping cursors or retried.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConsumptionStatus(str, Enum):
    """Result of processing a WorkEvent entry."""

    PROCESSED = "processed"       # First time seen, side effects executed
    DUPLICATE = "duplicate"       # Already processed, skipped
    FAILED = "failed"             # Processing error, will retry



@dataclass
class ProcessedEntry:
    """A single processed event with dedup metadata."""

    event_id: str
    activity_uid: str
    processed_at: str
    attempt_count: int = 1
    status: ConsumptionStatus = ConsumptionStatus.PROCESSED


@dataclass
class IdempotentConsumer:
    """Tracks processed events to guarantee at-most-once side effects.

    In production this is backed by Redis or a database table; the in-memory
    implementation here defines the contract and is used for testing.
    """

    _processed: dict[str, ProcessedEntry] = field(default_factory=dict)
    max_retained: int = 10_000

    def process(
        self,
        event_id: str,
        activity_uid: str,
        handler: Any,
        payload: dict[str, Any] | None = None,
    ) -> ConsumptionStatus:
        """Process an event exactly once. Returns the consumption status.

        If the event_id has been seen before, returns DUPLICATE and skips
        the handler. If the handler raises, records the failure for retry.
        """
        if event_id in self._processed:
            entry = self._processed[event_id]
            entry.attempt_count += 1
            return ConsumptionStatus.DUPLICATE

        try:
            if payload:
                handler(payload)
            else:
                handler()

            entry = ProcessedEntry(
                event_id=event_id,
                activity_uid=activity_uid,
                processed_at=_now_iso(),
                status=ConsumptionStatus.PROCESSED,
            )
        except Exception:
            entry = ProcessedEntry(
                event_id=event_id,
                activity_uid=activity_uid,
                processed_at=_now_iso(),
                status=ConsumptionStatus.FAILED,
            )
            self._processed[event_id] = entry
            raise

        self._processed[event_id] = entry
        self._evict_if_needed()
        return ConsumptionStatus.PROCESSED

    def is_processed(self, event_id: str) -> bool:
        return event_id in self._processed

    def get_entry(self, event_id: str) -> ProcessedEntry | None:
        return self._processed.get(event_id)

    def _evict_if_needed(self) -> None:
        if len(self._processed) <= self.max_retained:
            return
        # Evict oldest PROCESSED entries first (keep FAILED for retry tracking)
        sorted_entries = sorted(
            self._processed.items(),
            key=lambda kv: (kv[1].status != ConsumptionStatus.FAILED, kv[1].processed_at),
        )
        excess = len(self._processed) - self.max_retained
        for key, _ in sorted_entries[:excess]:
            if self._processed[key].status != ConsumptionStatus.FAILED:
                del self._processed[key]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
