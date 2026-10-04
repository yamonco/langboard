import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID
import pytest
from langboard_shared.core.broadcast import DispatcherModel
from langboard_shared.core.broadcast.BaseDispatcherQueue import BaseDispatcherQueue
from langboard_shared.core.broadcast.kafka.KafkaDispatcherQueue import KafkaDispatcherQueue
from langboard_shared.core.broadcast.memory.MemoryDispatcherQueue import MemoryDispatcherQueue
from langboard_shared.core.types import SnowflakeID
from pytest import MonkeyPatch


class FakeKafkaProducer:
    def __init__(self, **config: object) -> None:
        self.config = config
        self.messages: list[tuple[str, dict[str, object]]] = []
        self.delivery = Mock()

    def send(self, topic: str, value: dict[str, object]) -> Mock:
        self.messages.append((topic, value))
        return self.delivery


def test_kafka_dispatcher_publishes_inline_v2_envelope_without_redis_cache(
    monkeypatch: MonkeyPatch,
) -> None:
    environment = SimpleNamespace(
        BROADCAST_URLS=["kafka:9092"],
        BROADCAST_MAX_MESSAGE_BYTES=10 * 1024 * 1024,
        BROADCAST_PUBLISH_TIMEOUT_SECONDS=30,
    )
    cache_set = Mock()
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "Env", environment)
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "KafkaProducer", FakeKafkaProducer)
    monkeypatch.setattr("langboard_shared.core.caching.Cache.set", cache_set)

    queue = KafkaDispatcherQueue()
    queue.put(DispatcherModel(event="socket_publish", data={"id": SnowflakeID(123)}))

    assert isinstance(queue.producer, FakeKafkaProducer)
    assert queue.producer.config["bootstrap_servers"] == ["kafka:9092"]
    assert queue.producer.config["enable_idempotence"] is True
    assert queue.producer.config["max_request_size"] == 10 * 1024 * 1024
    queue.producer.delivery.get.assert_called_once_with(timeout=30)

    topic, envelope = queue.producer.messages[0]
    assert topic == "socket_publish"
    assert envelope["schema_version"] == "2"
    assert envelope["event"] == topic
    assert isinstance(envelope["occurred_at"], str)
    assert envelope["data"] == {"id": "123"}
    assert "cache_key" not in envelope
    UUID(str(envelope["event_id"]))

    cache_set.assert_not_called()


def test_kafka_dispatcher_accepts_event_and_data_arguments(monkeypatch: MonkeyPatch) -> None:
    environment = SimpleNamespace(
        BROADCAST_URLS=["kafka:9092"],
        BROADCAST_MAX_MESSAGE_BYTES=10 * 1024 * 1024,
        BROADCAST_PUBLISH_TIMEOUT_SECONDS=30,
    )
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "Env", environment)
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "KafkaProducer", FakeKafkaProducer)

    queue = KafkaDispatcherQueue()
    queue.put("socket_publish", {"value": "ok"})

    assert isinstance(queue.producer, FakeKafkaProducer)
    assert queue.producer.messages[0][1]["data"] == {"value": "ok"}


def test_kafka_dispatcher_rejects_oversized_inline_payload(monkeypatch: MonkeyPatch) -> None:
    environment = SimpleNamespace(
        BROADCAST_URLS=["kafka:9092"],
        BROADCAST_MAX_MESSAGE_BYTES=128,
        BROADCAST_PUBLISH_TIMEOUT_SECONDS=30,
    )
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "Env", environment)
    monkeypatch.setitem(KafkaDispatcherQueue.__init__.__globals__, "KafkaProducer", FakeKafkaProducer)

    queue = KafkaDispatcherQueue()

    with pytest.raises(ValueError, match="Broadcast payload exceeds"):
        queue.put("socket_publish", {"value": "x" * 256})

    assert isinstance(queue.producer, FakeKafkaProducer)
    assert queue.producer.messages == []


def test_memory_dispatcher_never_uses_legacy_redis_pointer(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    cache_set = Mock()
    monkeypatch.setitem(BaseDispatcherQueue._record_model.__globals__, "_BROADCAST_DIR", tmp_path)
    monkeypatch.setitem(BaseDispatcherQueue._record_model.__globals__, "Env", SimpleNamespace(CACHE_TYPE="redis"))
    monkeypatch.setattr("langboard_shared.core.caching.Cache.set", cache_set)

    MemoryDispatcherQueue().put("socket_publish", {"value": "ok"})

    files = list(tmp_path.glob("*-fileonly.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["data"] == {"value": "ok"}
    cache_set.assert_not_called()
