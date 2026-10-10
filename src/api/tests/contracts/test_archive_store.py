import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timedelta, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.archive_store import (  # noqa: E402
    ArchiveRecord,
    RetentionPolicy,
    StorageTier,
    classify_tier,
    eligible_for_deletion,
    total_size,
    verify_records,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 11, 0, 0, tzinfo=UTC)


def record(uid: str = "a1", archived_at: datetime = BASE, size: int = 100, **overrides) -> ArchiveRecord:
    defaults = dict(
        uid=uid,
        kind="card",
        project_uid="p1",
        payload={"title": "done work"},
        archived_at=archived_at,
        size_bytes=size,
    )
    defaults.update(overrides)
    return ArchiveRecord(**defaults)


class TestRetentionPolicy:
    def test_rejects_cold_before_hot(self):
        with pytest.raises(ValueError):
            RetentionPolicy(hot_days=30, cold_days=10)

    def test_accepts_valid_policy(self):
        assert RetentionPolicy(hot_days=30, cold_days=365).cold_days == 365


class TestArchiveRecord:
    def test_rejects_naive_timestamp(self):
        with pytest.raises(ValueError):
            record(archived_at=datetime(2026, 9, 19))

    def test_payload_round_trip_keeps_hash(self):
        original = record()
        restored = ArchiveRecord.from_payload(original.to_payload())
        assert restored == original

    def test_round_trip_detects_tampering(self):
        payload = record().to_payload()
        payload["payload"]["title"] = "tampered"
        with pytest.raises(ValueError):
            ArchiveRecord.from_payload(payload)


class TestTiering:
    def test_fresh_record_stays_hot(self):
        policy = RetentionPolicy(hot_days=30, cold_days=365)
        assert classify_tier(record(archived_at=BASE), policy, now=BASE + timedelta(days=5)) is StorageTier.HOT

    def test_expired_record_demotes_to_cold(self):
        policy = RetentionPolicy(hot_days=30, cold_days=365)
        assert classify_tier(record(archived_at=BASE), policy, now=BASE + timedelta(days=40)) is StorageTier.COLD

    def test_deletion_eligibility_follows_cold_days(self):
        policy = RetentionPolicy(hot_days=30, cold_days=365)
        assert not eligible_for_deletion(record(archived_at=BASE), policy, now=BASE + timedelta(days=40))
        assert eligible_for_deletion(record(archived_at=BASE), policy, now=BASE + timedelta(days=400))


class TestSizing:
    def test_total_size_sums(self):
        assert total_size([record(size=100), record(uid="a2", size=50)]) == 150


class TestVerifyRecords:
    def test_detects_hash_mismatch(self):
        good = record()
        expected = {good.uid: good.content_hash(), "ghost": "0" * 64}
        assert verify_records([good], expected) == []

        tampered = record(payload={"title": "changed"})
        assert verify_records([tampered], {tampered.uid: good.content_hash()}) == [tampered.uid]
