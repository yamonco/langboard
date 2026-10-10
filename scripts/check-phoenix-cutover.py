import argparse
import asyncio
import os
from aiosmtplib import SMTP
from crontab import CronTab
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import TopicPartition
from langboard_shared.ai.BoardChatAttachment import (
    LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
    LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
)
from langboard_shared.core.broker import Broker
from langboard_shared.domain.services import DomainService
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


def check_phoenix_fanout_caught_up() -> None:
    group_id = os.environ.get("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", "").strip()
    if not group_id:
        raise RuntimeError("Phoenix fanout consumer group is not configured")
    topic = "socket_publish"
    configured_topic = os.environ.get("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC")
    if configured_topic and configured_topic != topic:
        raise RuntimeError("Phoenix fanout source topic does not match the Python publisher")

    admin = KafkaAdminClient(bootstrap_servers=Env.BROADCAST_URLS)
    try:
        state = admin.describe_consumer_groups([group_id])[0].state
        if state != "Stable":
            raise RuntimeError(f"Phoenix fanout consumer group is not active: {group_id} ({state})")
        consumer = KafkaConsumer(
            bootstrap_servers=Env.BROADCAST_URLS,
            enable_auto_commit=False,
            allow_auto_create_topics=False,
        )
        try:
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                raise RuntimeError("Phoenix fanout source topic is missing")
            assignments = [TopicPartition(topic, partition) for partition in sorted(partitions)]
            offsets = admin.list_consumer_group_offsets(group_id)
            beginnings = consumer.beginning_offsets(assignments)
            ends = consumer.end_offsets(assignments)
            for partition in assignments:
                committed = offsets.get(partition)
                if (
                    committed is None
                    or not beginnings[partition] <= committed.offset <= ends[partition]
                    or committed.offset != ends[partition]
                ):
                    raise RuntimeError(f"Phoenix fanout consumer group is not caught up: {group_id} {partition}")
            print(f"Phoenix fanout consumer group is caught up: {group_id}")
        finally:
            consumer.close()
    finally:
        admin.close()


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
        asyncio.run(check_smtp_connection())
    except Exception:
        raise RuntimeError("Notification SMTP connection, TLS, or authentication failed from the API runtime") from None
    print("Notification email outbox and configured SMTP connection are available")


async def check_smtp_connection() -> None:
    client = SMTP(
        hostname=Env.MAIL_SERVER,
        port=Env.MAIL_PORT,
        username=Env.MAIL_USERNAME or None,
        password=Env.MAIL_PASSWORD or None,
        start_tls=Env.MAIL_STARTTLS,
        use_tls=Env.MAIL_SSL_TLS,
        timeout=5,
    )
    try:
        _ = await client.connect()
    finally:
        if client.is_connected:
            _ = await client.quit()


def check_email_review_queue() -> None:
    with DomainService.use() as service:
        notification_pending = bool(service.notification.get_email_deliveries_for_review(1))
        project_pending = service.project_email_notification.count_deliveries_for_review() > 0
    if notification_pending or project_pending:
        print(
            "Warning: failed or uncertain email deliveries remain quarantined for operator review "
            f"(notification={notification_pending}, project_activity={project_pending})"
        )
    else:
        print("Notification email review queue is empty")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--celery-only", action="store_true")
    args = parser.parse_args()
    if args.celery_only:
        check_required_celery_tasks()
    else:
        check_email_delivery_owner()
        check_required_celery_tasks()
        check_legacy_consumers_drained()
        check_phoenix_fanout_caught_up()
        check_email_review_queue()
