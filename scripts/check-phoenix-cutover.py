import argparse
import socket
from crontab import CronTab
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import TopicPartition
from langboard_shared.ai.BoardChatAttachment import (
    LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
    LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
)
from langboard_shared.core.broker import Broker
from langboard_shared.domain.services.factory.OllamaModelPullService import PULL_TASK
from langboard_shared.Env import Env
from langboard_shared.tasks.notifications.ProjectEmailNotificationQueue import (
    PROJECT_EMAIL_DELIVERY_TASK,
    PROJECT_EMAIL_FANOUT_TASK,
)
from psutil import process_iter


REQUIRED_CELERY_TASKS = (
    LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
    LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
    PROJECT_EMAIL_FANOUT_TASK,
    PROJECT_EMAIL_DELIVERY_TASK,
    PULL_TASK,
)

LEGACY_CONSUMERS = (
    ("socket-node-fanout", "socket_publish", False),
    ("notification-node-owner", "notification_publish", True),
)


def check_legacy_consumers_drained() -> None:
    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        consumer = KafkaConsumer(
            bootstrap_servers=Env.BROADCAST_URLS,
            enable_auto_commit=False,
            allow_auto_create_topics=False,
        )
        try:
            for suffix, topic, require_drained in LEGACY_CONSUMERS:
                group_id = f"{Env.PROJECT_NAME}-{suffix}"
                state = admin.describe_consumer_groups([group_id])[0].state
                if state not in {"Dead", "Empty"}:
                    raise RuntimeError(f"Legacy consumer group is active: {group_id} ({state})")

                if not require_drained:
                    print(f"Legacy fanout consumer group is inactive: {group_id}")
                    continue

                offsets = admin.list_consumer_group_offsets(group_id)
                partitions = consumer.partitions_for_topic(topic)
                if not partitions:
                    if offsets:
                        raise RuntimeError(f"Legacy consumer topic is missing with retained offsets: {topic}")
                    print(f"Legacy side-effect consumer group and topic never existed: {group_id}")
                    continue
                assignments = [TopicPartition(topic, partition) for partition in sorted(partitions)]
                beginnings = consumer.beginning_offsets(assignments)
                ends = consumer.end_offsets(assignments)
                for partition in assignments:
                    committed = offsets.get(partition)
                    beginning = beginnings[partition]
                    end = ends[partition]
                    if committed is None:
                        if beginning != end:
                            raise RuntimeError(f"Legacy consumer has uncommitted records: {group_id} {partition}")
                    elif not beginning <= committed.offset <= end or committed.offset != end:
                        raise RuntimeError(f"Legacy consumer has undrained records: {group_id} {partition}")
                print(f"Legacy side-effect consumer group is inactive and drained: {group_id}")
        finally:
            consumer.close()
    finally:
        admin.close()


def check_required_celery_tasks() -> None:
    workers = Broker.require_registered_tasks(REQUIRED_CELERY_TASKS, timeout=10)
    print(f"Required Celery tasks are registered on {len(workers)} worker(s)")


def check_email_delivery_owner() -> None:
    if not Env.NOTIFICATION_EMAIL_OUTBOX_ENABLED:
        raise RuntimeError("Notification email outbox must be enabled")
    if not Env.MAIL_SERVER or not Env.MAIL_FROM:
        raise RuntimeError("Notification email delivery requires MAIL_SERVER and MAIL_FROM")
    jobs = list(CronTab(user=True).find_comment("notification-web-fanout-recovery"))
    if (
        len(jobs) != 1
        or str(jobs[0].slices) != "* * * * *"
        or str(jobs[0].command) != ("/bin/bash /app/scripts/run_notification_recovery.sh")
    ):
        raise RuntimeError("Notification email outbox recovery cron is not registered")
    if not any(process.info.get("name") == "cron" for process in process_iter(["name"])):
        raise RuntimeError("Notification email outbox recovery cron is not running")
    try:
        with socket.create_connection((Env.MAIL_SERVER, Env.MAIL_PORT), timeout=3):
            pass
    except OSError as exc:
        raise RuntimeError("Notification SMTP server is unreachable from the API runtime") from exc
    print("Notification email outbox is enabled")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--celery-only", action="store_true")
    args = parser.parse_args()
    check_required_celery_tasks()
    if not args.celery_only:
        check_email_delivery_owner()
        check_legacy_consumers_drained()
