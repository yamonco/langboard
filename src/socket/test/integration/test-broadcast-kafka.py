import json
from time import monotonic
from uuid import UUID, uuid4
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from langboard_shared.core.broadcast.kafka.KafkaDispatcherQueue import KafkaDispatcherQueue, _partition_key
from langboard_shared.Env import Env


def main() -> None:
    if not Env.BROADCAST_URLS:
        raise RuntimeError("The Kafka broadcast probe requires Kafka configuration")

    probe_id = uuid4().hex
    topic = f"broadcast-envelope-probe-{probe_id}"
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    consumer: KafkaConsumer | None = None
    queue = KafkaDispatcherQueue()

    try:
        admin.create_topics([NewTopic(name=topic, num_partitions=3, replication_factor=1)])
        consumer = KafkaConsumer(
            bootstrap_servers=Env.BROADCAST_URLS,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=f"{topic}-consumer",
            consumer_timeout_ms=30_000,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        consumer.subscribe([topic])
        deadline = monotonic() + 30
        while not consumer.assignment() and monotonic() < deadline:
            consumer.poll(timeout_ms=250)
        if not consumer.assignment():
            raise RuntimeError("Kafka did not assign the probe topic before the deadline")

        queue.put(topic, {"probe_id": probe_id, "delivery": "inline-without-redis"})
        message = next(iter(consumer))
        envelope = message.value

        assert "cache_key" not in envelope
        assert envelope["schema_version"] == "2"
        assert envelope["event"] == topic
        assert envelope["occurred_at"]
        assert envelope["data"] == {"probe_id": probe_id, "delivery": "inline-without-redis"}
        UUID(envelope["event_id"])

        assert queue.producer is not None
        scope = {"publish_models": {"topic": "user_private", "topic_id": probe_id}}
        key = _partition_key("socket_publish", scope)
        first = queue.producer.send(topic, {"probe_id": probe_id, "delivery": "keyed-first"}, key=key).get(timeout=10)
        second = queue.producer.send(topic, {"probe_id": probe_id, "delivery": "keyed-second"}, key=key).get(timeout=10)
        assert first.partition == second.partition
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
