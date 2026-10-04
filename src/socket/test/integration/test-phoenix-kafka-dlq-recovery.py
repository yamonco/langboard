import json
import logging
import os
from hashlib import sha256
from time import monotonic
from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import NewTopic
from langboard_shared.Env import Env


SOCKET_TOPIC = os.environ.get("PHOENIX_DLQ_TEST_SOURCE_TOPIC", "socket_publish")

logging.getLogger("kafka").setLevel(logging.WARNING)


def _payload(probe_id: str) -> bytes:
    return json.dumps({"dlq_recovery_probe": probe_id}, separators=(",", ":")).encode()


def _change_topic(create: bool) -> None:
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        candidates = {SOCKET_TOPIC, os.environ.get("PHOENIX_DLQ_TEST_TOPIC", "")}
        topics = candidates - {""}
        if create:
            admin.create_topics(
                [NewTopic(name=topic, num_partitions=1, replication_factor=1) for topic in sorted(topics)]
            )
        else:
            existing = topics & set(admin.list_topics())
            if existing:
                admin.delete_topics(sorted(existing))
    finally:
        admin.close()


def _produce(probe_id: str) -> None:
    producer = KafkaProducer(bootstrap_servers=Env.BROADCAST_URLS, acks="all", enable_idempotence=True)
    try:
        record = producer.send(SOCKET_TOPIC, _payload(probe_id)).get(timeout=10)
        print(f"{record.partition}:{record.offset}")
    finally:
        producer.close()


def _assert_uncommitted(group_id: str, partition: int, offset: int) -> None:
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        committed = admin.list_consumer_group_offsets(group_id).get(TopicPartition(SOCKET_TOPIC, partition))
        if committed is not None and committed.offset > offset:
            raise AssertionError(f"Rejected source offset {offset} was committed as {committed.offset}")
    finally:
        admin.close()


def _assert_delivered(probe_id: str, partition: int, offset: int, topic: str) -> None:
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=Env.BROADCAST_URLS,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"{topic}-{probe_id}",
        value_deserializer=lambda value: json.loads(value.decode()),
    )
    digest = sha256(_payload(probe_id)).hexdigest()
    deadline = monotonic() + 30
    try:
        while monotonic() < deadline:
            for messages in consumer.poll(timeout_ms=250).values():
                for message in messages:
                    record = message.value
                    if record.get("payload_sha256") != digest:
                        continue
                    assert record["reason"] == "invalid_broker_envelope"
                    assert record["source"] == {
                        "topic": SOCKET_TOPIC,
                        "partition": partition,
                        "offset": offset,
                    }
                    print("Phoenix replayed the rejected source record into the dead-letter topic")
                    return
        raise AssertionError("Phoenix did not replay the rejected source record after restart")
    finally:
        consumer.close()


if __name__ == "__main__":
    phase = os.environ["PHOENIX_DLQ_TEST_PHASE"]
    probe_id = os.environ["PHOENIX_DLQ_TEST_ID"]
    if phase == "create_topic":
        _change_topic(create=True)
    elif phase == "delete_topic":
        _change_topic(create=False)
    elif phase == "produce":
        _produce(probe_id)
    elif phase == "assert_uncommitted":
        _assert_uncommitted(
            os.environ["PHOENIX_DLQ_TEST_GROUP"],
            int(os.environ["PHOENIX_DLQ_TEST_PARTITION"]),
            int(os.environ["PHOENIX_DLQ_TEST_OFFSET"]),
        )
    elif phase == "assert_delivered":
        _assert_delivered(
            probe_id,
            int(os.environ["PHOENIX_DLQ_TEST_PARTITION"]),
            int(os.environ["PHOENIX_DLQ_TEST_OFFSET"]),
            os.environ["PHOENIX_DLQ_TEST_TOPIC"],
        )
    else:
        raise ValueError(f"Unknown probe phase: {phase}")
