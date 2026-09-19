import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.archive_store import ArchiveRecord, RetentionPolicy  # noqa: E402
from langboard_shared.domain.contracts.archive_transfer import (  # noqa: E402
    MAX_BATCH_BYTES,
    TransferManifest,
    manifest_covers,
    plan_hot_to_cold,
    plan_restore,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
POLICY = RetentionPolicy(hot_days=30, cold_days=365)


def record(uid: str, archived_at: datetime = BASE, size: int = 100) -> ArchiveRecord:
    return ArchiveRecord(
        uid=uid,
        kind="card",
        project_uid="p1",
        payload={"title": uid},
        archived_at=archived_at,
        size_bytes=size,
    )


class TestTransferManifest:
    def test_rejects_empty_and_unknown_direction(self):
        with pytest.raises(ValueError):
            TransferManifest(manifest_uid="m", direction="sideways", record_uids=("a",), total_bytes=1, content_hashes={"a": "x"})
        with pytest.raises(ValueError):
            TransferManifest(manifest_uid="m", direction="hot_to_cold", record_uids=(), total_bytes=0, content_hashes={})

    def test_hashes_must_cover_records(self):
        with pytest.raises(ValueError):
            TransferManifest(
                manifest_uid="m",
                direction="hot_to_cold",
                record_uids=("a", "b"),
                total_bytes=2,
                content_hashes={"a": "x"},
            )


class TestPlanHotToCold:
    def test_selects_only_expired(self):
        fresh = record("fresh", archived_at=BASE)
        old = record("old", archived_at=BASE - timedelta(days=45))
        manifest = plan_hot_to_cold([fresh, old], POLICY, now=BASE)
        assert manifest is not None
        assert manifest.record_uids == ("old",)
        assert manifest.direction == "hot_to_cold"

    def test_returns_none_when_nothing_expired(self):
        assert plan_hot_to_cold([record("fresh")], POLICY, now=BASE) is None

    def test_oversized_batch_rejected(self):
        huge = record("huge", archived_at=BASE - timedelta(days=60), size=MAX_BATCH_BYTES + 1)
        with pytest.raises(ValueError):
            plan_hot_to_cold([huge], POLICY, now=BASE)


class TestPlanRestore:
    def test_restore_selected_uids(self):
        records = [record("a", archived_at=BASE - timedelta(days=60)), record("b", archived_at=BASE - timedelta(days=60))]
        manifest = plan_restore(records, ["b"])
        assert manifest.record_uids == ("b",)
        assert manifest.direction == "cold_to_hot"

    def test_unknown_uid_rejected(self):
        with pytest.raises(ValueError):
            plan_restore([record("a")], ["ghost"])


class TestManifestCovers:
    def test_detects_drift_after_planning(self):
        original = record("a", archived_at=BASE - timedelta(days=60))
        manifest = plan_hot_to_cold([original], POLICY, now=BASE)
        changed = ArchiveRecord(
            uid="a",
            kind="card",
            project_uid="p1",
            payload={"title": "edited"},
            archived_at=original.archived_at,
            size_bytes=original.size_bytes,
        )
        assert manifest_covers(manifest, [original]) == []
        assert manifest_covers(manifest, [changed]) == ["a"]
