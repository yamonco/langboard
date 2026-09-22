import json
from time import monotonic
from uuid import UUID, uuid4
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from langboard_shared.core.broadcast.kafka.KafkaDispatcherQueue import KafkaDispatcherQueue
from langboard_shared.core.caching import Cache
from langboard_shared.Env import Env


def main() -> None:
    if Env.CACHE_TYPE != "redis" or not Env.BROADCAST_URLS:
        raise RuntimeError("The Kafka broadcast probe requires Redis and Kafka configuration")

    probe_id = uuid4().hex
    topic = f"broadcast-envelope-probe-{probe_id}"
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    consumer: KafkaConsumer | None = None
    queue = KafkaDispatcherQueue()

    try:
        admin.create_topics([NewTopic(name=topic, num_partitions=1, replication_factor=1)])
        consumer = KafkaConsumer(
            bootstrap_servers=Env.BROADCAST_URLS,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=f"{topic}-consumer",
            consumer_timeout_ms=15_000,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        consumer.subscribe([topic])
        deadline = monotonic() + 15
        while not consumer.assignment() and monotonic() < deadline:
            consumer.poll(timeout_ms=250)
        if not consumer.assignment():
            raise RuntimeError("Kafka did not assign the probe topic before the deadline")

        queue.put(topic, {"probe_id": probe_id, "delivery": "inline-after-cache-delete"})
        message = next(iter(consumer))
        envelope = message.value
        cache_key = envelope["cache_key"]
        Cache.delete(cache_key)

        assert Cache.get(cache_key) is None
        assert envelope["schema_version"] == "2"
        assert envelope["event"] == topic
        assert envelope["occurred_at"]
        assert envelope["data"] == {"probe_id": probe_id, "delivery": "inline-after-cache-delete"}
        UUID(envelope["event_id"])
    finally:
        if consumer:
            consumer.close()
        if queue.producer:
            queue.producer.close()
        try:
            admin.delete_topics([topic])
        finally:
            admin.close()


if __name__ == "__main__":
    main()
