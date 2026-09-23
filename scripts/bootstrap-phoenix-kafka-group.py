import os
import time
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import OffsetAndMetadata, TopicPartition
from langboard_shared.Env import Env


SOURCE_TOPIC = os.environ.get("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC", "socket_publish")
WAIT_TIMEOUT_SECONDS = 60


def bootstrap_group(group_id: str) -> None:
    if not group_id:
        raise ValueError("PHOENIX_FANOUT_GROUP_ID is required")

    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        state = admin.describe_consumer_groups([group_id])[0].state
        if state not in {"Dead", "Empty"}:
            raise RuntimeError(f"Refusing to change an active consumer group: {state}")

        existing = admin.list_consumer_group_offsets(group_id)
        consumer = KafkaConsumer(
            bootstrap_servers=Env.BROADCAST_URLS,
            group_id=group_id,
            enable_auto_commit=False,
        )
        try:
            partitions = consumer.partitions_for_topic(SOURCE_TOPIC)
            if not partitions:
                raise RuntimeError(f"Source topic is missing: {SOURCE_TOPIC}")

            assignments = [TopicPartition(SOURCE_TOPIC, partition) for partition in sorted(partitions)]
            if existing:
                if any(partition not in existing or existing[partition].offset < 0 for partition in assignments):
                    raise RuntimeError("Refusing to bootstrap a partially committed consumer group")
                print(f"Consumer group already has source offsets: {group_id}")
                return

            consumer.assign(assignments)
            ends = consumer.end_offsets(assignments)
            consumer.commit(
                {
                    partition: OffsetAndMetadata(ends[partition], "phoenix-initial-offset", -1)
                    for partition in assignments
                }
            )
            if any(consumer.committed(partition) != ends[partition] for partition in assignments):
                raise RuntimeError("Could not verify initial consumer group offsets")
            print(f"Initialized consumer group at current source end: {group_id}")
        finally:
            consumer.close()
    finally:
        admin.close()


def wait_for_caught_up_group(group_id: str) -> None:
    if not group_id:
        raise ValueError("PHOENIX_FANOUT_GROUP_ID is required")

    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    consumer = KafkaConsumer(
        bootstrap_servers=Env.BROADCAST_URLS,
        group_id=group_id,
        enable_auto_commit=False,
    )
    try:
        partitions = consumer.partitions_for_topic(SOURCE_TOPIC)
        if not partitions:
            raise RuntimeError(f"Source topic is missing: {SOURCE_TOPIC}")

        assignments = [TopicPartition(SOURCE_TOPIC, partition) for partition in sorted(partitions)]
        consumer.assign(assignments)
        while time.monotonic() < deadline:
            ends = consumer.end_offsets(assignments)
            caught_up = True
            for partition in assignments:
                offset = consumer.committed(partition)
                if offset is None or offset < ends[partition]:
                    caught_up = False
                    break
            if caught_up:
                print(f"Consumer group is caught up: {group_id}")
                return
            time.sleep(1)

        raise RuntimeError(f"Consumer group did not catch up within {WAIT_TIMEOUT_SECONDS} seconds: {group_id}")
    finally:
        consumer.close()


def require_existing_group(group_id: str) -> None:
    if not group_id:
        raise ValueError("PHOENIX_FANOUT_GROUP_ID is required")

    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        consumer = KafkaConsumer(bootstrap_servers=Env.BROADCAST_URLS, enable_auto_commit=False)
        try:
            partitions = consumer.partitions_for_topic(SOURCE_TOPIC)
            if not partitions:
                raise RuntimeError(f"Source topic is missing: {SOURCE_TOPIC}")

            assignments = [TopicPartition(SOURCE_TOPIC, partition) for partition in sorted(partitions)]
            offsets = admin.list_consumer_group_offsets(group_id)
            beginnings = consumer.beginning_offsets(assignments)
            ends = consumer.end_offsets(assignments)
            invalid = [
                partition.partition
                for partition in assignments
                if partition not in offsets or not beginnings[partition] <= offsets[partition].offset <= ends[partition]
            ]
            if invalid:
                raise RuntimeError(f"Phoenix fanout group has missing or expired source offsets: {group_id} {invalid}")
            print(f"Phoenix fanout group has retained source offsets: {group_id}")
        finally:
            consumer.close()
    finally:
        admin.close()


if __name__ == "__main__":
    group_id = os.environ["PHOENIX_FANOUT_GROUP_ID"].strip()
    if os.getenv("PHOENIX_FANOUT_REQUIRE_EXISTING") == "1":
        require_existing_group(group_id)
    elif os.getenv("PHOENIX_FANOUT_WAIT_FOR_CATCH_UP") == "1":
        wait_for_caught_up_group(group_id)
    else:
        bootstrap_group(group_id)
