import os
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts.idempotency import (  # noqa: E402
    ConsumptionStatus,
    IdempotentConsumer,
)


def test_first_process_returns_processed():
    consumer = IdempotentConsumer()
    called = []
    status = consumer.process("evt-1", "act-1", lambda: called.append(1))
    assert status == ConsumptionStatus.PROCESSED
    assert len(called) == 1


def test_second_process_returns_duplicate():
    consumer = IdempotentConsumer()
    consumer.process("evt-1", "act-1", lambda: None)
    status = consumer.process("evt-1", "act-1", lambda: None)
    assert status == ConsumptionStatus.DUPLICATE


def test_duplicate_does_not_re_execute_handler():
    consumer = IdempotentConsumer()
    called = []
    consumer.process("evt-1", "act-1", lambda: called.append(1))
    consumer.process("evt-1", "act-1", lambda: called.append(2))
    assert called == [1]


def test_failed_event_can_retry():
    consumer = IdempotentConsumer()
    with pytest.raises(ValueError):
        consumer.process("evt-fail", "act-1", lambda: (_ for _ in ()).throw(ValueError("boom")))
    entry = consumer.get_entry("evt-fail")
    assert entry is not None
    assert entry.status == ConsumptionStatus.FAILED


def test_is_processed():
    consumer = IdempotentConsumer()
    assert not consumer.is_processed("evt-x")
    consumer.process("evt-x", "act-1", lambda: None)
    assert consumer.is_processed("evt-x")


def test_eviction_keeps_failed_entries():
    consumer = IdempotentConsumer(max_retained=3)
    # Process 3 successful + 1 failed
    consumer.process("e1", "a1", lambda: None)
    consumer.process("e2", "a2", lambda: None)
    consumer.process("e3", "a3", lambda: None)
    with pytest.raises(ValueError):
        consumer.process("e4", "a4", lambda: (_ for _ in ()).throw(ValueError("fail")))
    # Process one more to trigger eviction
    consumer.process("e5", "a5", lambda: None)
    # Failed entry should be retained
    assert consumer.is_processed("e4")
    # At least one successful entry should be evicted
    assert len(consumer._processed) <= 4


def test_attempt_count_increments_on_duplicate():
    consumer = IdempotentConsumer()
    consumer.process("evt-1", "act-1", lambda: None)
    consumer.process("evt-1", "act-1", lambda: None)
    consumer.process("evt-1", "act-1", lambda: None)
    entry = consumer.get_entry("evt-1")
    assert entry is not None
    assert entry.attempt_count == 3
