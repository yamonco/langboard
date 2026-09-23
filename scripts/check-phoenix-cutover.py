import argparse
import os
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import TopicPartition
from langboard_shared.ai.BoardChatAttachment import (
    LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
    LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
)
from langboard_shared.core.broker import Broker
from langboard_shared.domain.services.factory.OllamaModelPullService import PULL_TASK
from langboard_shared.Env import Env
from langboard_shared.tasks.notifications.ProjectEmailNotificationQueue import PROJECT_EMAIL_FANOUT_TASK


REQUIRED_CELERY_TASKS = (
    LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
    LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
    PROJECT_EMAIL_FANOUT_TASK,
    PULL_TASK,
)


def check_required_celery_tasks() -> None:
    workers = Broker.require_registered_tasks(REQUIRED_CELERY_TASKS, timeout=10)
    print(f"Required Celery tasks are registered on {len(workers)} worker(s)")


def check_consumer_group_stopped(
    admin: KafkaAdminClient,
    label: str,
    environment_key: str,
    default_suffix: str,
) -> str:
    group_id = os.getenv(environment_key) or f"{Env.PROJECT_NAME}-{default_suffix}"
    description = admin.describe_consumer_groups([group_id])[0]
    if description.state not in {"Dead", "Empty"}:
        raise RuntimeError(f"{label} consumer group is still active: {group_id} ({description.state})")
    print(f"{label} consumer group is stopped: {group_id}")
    return group_id


def check_consumer_group_drained(
    admin: KafkaAdminClient,
    consumer: KafkaConsumer,
    label: str,
    environment_key: str,
    topic: str,
    default_suffix: str,
) -> None:
    group_id = check_consumer_group_stopped(admin, label, environment_key, default_suffix)

    partitions = consumer.partitions_for_topic(topic)
    if not partitions:
        raise RuntimeError(f"Source topic is missing: {topic}")

    assignments = [TopicPartition(topic, partition) for partition in sorted(partitions)]
    beginnings = consumer.beginning_offsets(assignments)
    ends = consumer.end_offsets(assignments)
    offsets = admin.list_consumer_group_offsets(group_id)
    missing = [
        partition.partition
        for partition in assignments
        if partition not in offsets and ends[partition] > beginnings[partition]
    ]
    behind = [
        partition.partition
        for partition in assignments
        if partition in offsets and offsets[partition].offset < ends[partition]
    ]
    if missing or behind:
        raise RuntimeError(
            f"{label} consumer group is not drained: group={group_id} topic={topic} missing={missing} behind={behind}"
        )

    print(f"{label} consumer group is drained: {group_id}")


def check_legacy_consumer_groups() -> None:
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    consumer = KafkaConsumer(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        check_consumer_group_stopped(admin, "Node fanout", "BROADCAST_NODE_FANOUT_CONSUMER_GROUP", "socket-node-fanout")
        check_consumer_group_drained(
            admin,
            consumer,
            "Node notification side effect",
            "BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP",
            "notification_publish",
            "notification-node-owner",
        )
    finally:
        consumer.close()
        admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--celery-only", action="store_true")
    args = parser.parse_args()
    check_required_celery_tasks()
    if not args.celery_only:
        check_legacy_consumer_groups()
