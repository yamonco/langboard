"""Archive cold store tiering contracts.

Defines the storage tiers, archived record envelopes with integrity
hashes, retention policy, and tier classification for archived board
content. Pure value logic; the physical store stays behind an
interface.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from typing import Any


class StorageTier(str, Enum):
    """Lifecycle tiers for archived content."""

    HOT = "hot"
    COLD = "cold"


@dataclass(frozen=True)
class RetentionPolicy:
    """How long content stays in each tier."""

    hot_days: int = 30
    cold_days: int = 365

    def __post_init__(self) -> None:
        if self.hot_days < 0 or self.cold_days < self.hot_days:
            raise ValueError("cold_days must be at least hot_days and both non-negative")


@dataclass(frozen=True)
class ArchiveRecord:
    """One archived board record with an integrity hash."""

    uid: str
    kind: str  # "card" | "comment" | "wiki" | "checklist"
    project_uid: str
    payload: dict[str, Any]
    archived_at: datetime
    size_bytes: int

    def __post_init__(self) -> None:
        if not self.uid or not self.kind.strip() or not self.project_uid:
            raise ValueError("uid, kind and project_uid are required")
        if self.archived_at.tzinfo is None:
            raise ValueError("archived_at must be timezone-aware")
        if self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")

    def content_hash(self) -> str:
        """Deterministic integrity hash over kind and payload."""

        canonical = json.dumps({"kind": self.kind, "payload": self.payload}, sort_keys=True, ensure_ascii=False)
        return sha256(canonical.encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the physical store."""

        return {
            "uid": self.uid,
            "kind": self.kind,
            "project_uid": self.project_uid,
            "payload": self.payload,
            "archived_at": self.archived_at.isoformat(),
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash(),
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "ArchiveRecord":
        """Restore a record and verify its integrity hash."""

        record = ArchiveRecord(
            uid=payload["uid"],
            kind=payload["kind"],
            project_uid=payload["project_uid"],
            payload=payload["payload"],
            archived_at=datetime.fromisoformat(payload["archived_at"]),
            size_bytes=payload["size_bytes"],
        )
        expected = payload.get("content_hash")
        if expected and expected != record.content_hash():
            raise ValueError(f"integrity hash mismatch for {record.uid}")
        return record


def classify_tier(record: ArchiveRecord, policy: RetentionPolicy, now: datetime | None = None) -> StorageTier:
    """Return the tier a record belongs to under the policy."""

    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age = now - record.archived_at
    return StorageTier.COLD if age >= timedelta(days=policy.hot_days) else StorageTier.HOT


def eligible_for_deletion(record: ArchiveRecord, policy: RetentionPolicy, now: datetime | None = None) -> bool:
    """Whether a record has outlived the full retention window."""

    if now is None:
        now = datetime.now(timezone.utc)
    age = now - record.archived_at
    return age >= timedelta(days=policy.cold_days)


def total_size(records: list[ArchiveRecord]) -> int:
    """Sum record sizes for capacity planning."""

    return sum(record.size_bytes for record in records)


def verify_records(records: list[ArchiveRecord], expected_hashes: dict[str, str]) -> list[str]:
    """Return uids whose hash disagrees with the expected manifest."""

    mismatched = []
    for record in records:
        expected = expected_hashes.get(record.uid)
        if expected is not None and expected != record.content_hash():
            mismatched.append(record.uid)
    return mismatched
