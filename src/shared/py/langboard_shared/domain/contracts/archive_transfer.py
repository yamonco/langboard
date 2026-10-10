"""Card cold-store transfer planning.

Selects archived records for hot→cold demotion, batches them into
all-or-nothing manifests, and plans restores back to hot. Pure
planning over ArchiveRecord values from archive_store.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from .archive_store import ArchiveRecord, RetentionPolicy, StorageTier, classify_tier


MAX_BATCH_BYTES = 512 * 1024 * 1024
MAX_BATCH_RECORDS = 5_000


@dataclass(frozen=True)
class TransferManifest:
    """An all-or-nothing batch of records moving between tiers."""

    manifest_uid: str
    direction: str  # "hot_to_cold" | "cold_to_hot"
    record_uids: tuple[str, ...]
    total_bytes: int
    content_hashes: dict[str, str]

    def __post_init__(self) -> None:
        if not self.manifest_uid:
            raise ValueError("manifest_uid is required")
        if self.direction not in ("hot_to_cold", "cold_to_hot"):
            raise ValueError("direction must be hot_to_cold or cold_to_hot")
        if not self.record_uids:
            raise ValueError("a manifest cannot be empty")
        if len(self.record_uids) != len(set(self.record_uids)):
            raise ValueError("duplicate record uids in manifest")
        if len(self.record_uids) > MAX_BATCH_RECORDS:
            raise ValueError(f"a manifest holds at most {MAX_BATCH_RECORDS} records")
        if self.total_bytes > MAX_BATCH_BYTES:
            raise ValueError(f"a manifest holds at most {MAX_BATCH_BYTES} bytes")
        if set(self.content_hashes) != set(self.record_uids):
            raise ValueError("content hashes must cover exactly the manifest records")


def plan_hot_to_cold(
    records: Sequence[ArchiveRecord],
    policy: RetentionPolicy,
    now: datetime,
    *,
    manifest_uid: str = "manifest:hot-to-cold",
) -> TransferManifest | None:
    """Build the demotion manifest for records whose hot window expired.

    Records already cold are skipped. Returns None when nothing to
    move. A batch exceeding the limits raises so the caller re-plans
    with smaller input.
    """

    candidates = [
        record
        for record in records
        if classify_tier(record, policy, now) is StorageTier.COLD and record.size_bytes >= 0
    ]
    if not candidates:
        return None
    return TransferManifest(
        manifest_uid=manifest_uid,
        direction="hot_to_cold",
        record_uids=tuple(record.uid for record in candidates),
        total_bytes=sum(record.size_bytes for record in candidates),
        content_hashes={record.uid: record.content_hash() for record in candidates},
    )


def plan_restore(
    records: Sequence[ArchiveRecord],
    uids: Sequence[str],
    *,
    manifest_uid: str = "manifest:cold-to-hot",
) -> TransferManifest:
    """Plan an explicit restore of selected records back to hot."""

    wanted = set(uids)
    if not wanted:
        raise ValueError("restore requires at least one uid")
    selected = {record.uid: record for record in records}
    missing = wanted - set(selected)
    if missing:
        raise ValueError(f"unknown restore uids: {sorted(missing)}")
    chosen = [selected[uid] for uid in uids]
    return TransferManifest(
        manifest_uid=manifest_uid,
        direction="cold_to_hot",
        record_uids=tuple(record.uid for record in chosen),
        total_bytes=sum(record.size_bytes for record in chosen),
        content_hashes={record.uid: record.content_hash() for record in chosen},
    )


def manifest_covers(manifest: TransferManifest, records: Sequence[ArchiveRecord]) -> list[str]:
    """Return record uids whose hash no longer matches the manifest."""

    current = {record.uid: record.content_hash() for record in records}
    return [uid for uid in manifest.record_uids if current.get(uid) != manifest.content_hashes[uid]]
