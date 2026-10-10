import asyncio
import runpy
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Any, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock, Mock
import pytest
from kafka.structs import OffsetAndMetadata, TopicPartition


_scripts = Path(__file__).resolve().parents[4] / "scripts"
_gate = runpy.run_path(str(_scripts / "check-phoenix-cutover.py"))
_bootstrap = runpy.run_path(str(_scripts / "bootstrap-phoenix-kafka-group.py"))
check_required_celery_tasks = cast(Callable[[], None], _gate["check_required_celery_tasks"])
check_email_delivery_owner = cast(Callable[[], None], _gate["check_email_delivery_owner"])
check_smtp_connection = cast(Callable[[], Coroutine[Any, Any, None]], _gate["check_smtp_connection"])
check_email_review_queue = cast(Callable[[], None], _gate["check_email_review_queue"])
check_legacy_consumers_drained = cast(Callable[[], None], _gate["check_legacy_consumers_drained"])
check_phoenix_fanout_caught_up = cast(Callable[[], None], _gate["check_phoenix_fanout_caught_up"])
require_existing_group = cast(FunctionType, _bootstrap["require_existing_group"])


def test_phoenix_owner_requires_email_fanout_and_delivery_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = Mock()
    broker.require_registered_tasks.return_value = {"worker": []}
    monkeypatch.setitem(check_required_celery_tasks.__globals__, "Broker", broker)

    check_required_celery_tasks()

    tasks = broker.require_registered_tasks.call_args.args[0]
    assert any(task.endswith(".fanout_project_activity_email") for task in tasks)
    assert any(task.endswith(".deliver_project_activity_email") for task in tasks)


def test_phoenix_owner_requires_notification_email_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        check_email_delivery_owner.__globals__, "Env", SimpleNamespace(NOTIFICATION_EMAIL_OUTBOX_ENABLED=False)
    )
    with pytest.raises(RuntimeError, match="Notification email outbox must be enabled"):
        check_email_delivery_owner()


@pytest.mark.parametrize(
    ("mail_server", "mail_from"),
    [("", "noreply@example.test"), ("smtp.example.test", "")],
)
def test_phoenix_owner_requires_smtp_delivery_configuration(
    monkeypatch: pytest.MonkeyPatch, mail_server: str, mail_from: str
) -> None:
    monkeypatch.setitem(
        check_email_delivery_owner.__globals__,
        "Env",
        SimpleNamespace(NOTIFICATION_EMAIL_OUTBOX_ENABLED=True, MAIL_SERVER=mail_server, MAIL_FROM=mail_from),
    )
    with pytest.raises(RuntimeError, match="MAIL_SERVER and MAIL_FROM"):
        check_email_delivery_owner()


@pytest.mark.parametrize(
    "jobs,processes,expected_error",
    [
        ([], [SimpleNamespace(info={"name": "cron"})], "not registered"),
        (
            [SimpleNamespace(command="/bin/bash /app/scripts/run_notification_recovery.sh", slices="* * * * *")],
            [],
            "not running",
        ),
    ],
)
def test_phoenix_owner_requires_notification_recovery_cron(
    monkeypatch: pytest.MonkeyPatch, jobs: list[SimpleNamespace], processes: list[SimpleNamespace], expected_error: str
) -> None:
    monkeypatch.setitem(
        check_email_delivery_owner.__globals__,
        "Env",
        SimpleNamespace(
            NOTIFICATION_EMAIL_OUTBOX_ENABLED=True,
            MAIL_SERVER="smtp.example.test",
            MAIL_FROM="noreply@example.test",
        ),
    )
    cron = Mock()
    cron.find_comment.return_value = jobs
    monkeypatch.setitem(check_email_delivery_owner.__globals__, "CronTab", Mock(return_value=cron))
    monkeypatch.setitem(check_email_delivery_owner.__globals__, "process_iter", Mock(return_value=processes))

    with pytest.raises(RuntimeError, match=expected_error):
        check_email_delivery_owner()


def test_phoenix_owner_requires_smtp_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    env = SimpleNamespace(
        NOTIFICATION_EMAIL_OUTBOX_ENABLED=True,
        MAIL_SERVER="smtp.example.test",
        MAIL_PORT=587,
        MAIL_FROM="noreply@example.test",
    )
    monkeypatch.setitem(check_email_delivery_owner.__globals__, "Env", env)
    cron = Mock()
    cron.find_comment.return_value = [
        SimpleNamespace(command="/bin/bash /app/scripts/run_notification_recovery.sh", slices="* * * * *")
    ]
    monkeypatch.setitem(check_email_delivery_owner.__globals__, "CronTab", Mock(return_value=cron))
    monkeypatch.setitem(
        check_email_delivery_owner.__globals__,
        "process_iter",
        Mock(return_value=[SimpleNamespace(info={"name": "cron"})]),
    )
    connect = AsyncMock()
    monkeypatch.setitem(check_email_delivery_owner.__globals__, "check_smtp_connection", connect)

    check_email_delivery_owner()
    connect.assert_awaited_once_with()

    connect.side_effect = ConnectionRefusedError()
    with pytest.raises(RuntimeError, match="SMTP connection, TLS, or authentication failed"):
        check_email_delivery_owner()


def test_phoenix_owner_uses_delivery_smtp_security_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    env = SimpleNamespace(
        MAIL_SERVER="smtp.example.test",
        MAIL_PORT=587,
        MAIL_USERNAME="sender",
        MAIL_PASSWORD="secret",
        MAIL_STARTTLS=True,
        MAIL_SSL_TLS=False,
    )
    client = Mock(is_connected=True)
    client.connect = AsyncMock()
    client.quit = AsyncMock()
    smtp = Mock(return_value=client)
    monkeypatch.setitem(check_smtp_connection.__globals__, "Env", env)
    monkeypatch.setitem(check_smtp_connection.__globals__, "SMTP", smtp)

    asyncio.run(check_smtp_connection())

    smtp.assert_called_once_with(
        hostname=env.MAIL_SERVER,
        port=env.MAIL_PORT,
        username=env.MAIL_USERNAME,
        password=env.MAIL_PASSWORD,
        start_tls=env.MAIL_STARTTLS,
        use_tls=env.MAIL_SSL_TLS,
        timeout=5,
    )
    client.connect.assert_awaited_once_with()
    client.quit.assert_awaited_once_with()


@pytest.mark.parametrize("review_pending", [False, True])
def test_phoenix_owner_reports_quarantined_notification_emails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], review_pending: bool
) -> None:
    service = Mock()
    service.notification.get_email_deliveries_for_review.return_value = [Mock()] if review_pending else []
    service.project_email_notification.count_deliveries_for_review.return_value = 0
    domain = MagicMock()
    domain.use.return_value.__enter__.return_value = service
    monkeypatch.setitem(check_email_review_queue.__globals__, "DomainService", domain)

    check_email_review_queue()
    output = capsys.readouterr().out
    assert ("remain quarantined for operator review" in output) is review_pending
    service.notification.get_email_deliveries_for_review.assert_called_once_with(1)


def test_phoenix_owner_reports_quarantined_project_activity_emails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Mock()
    service.notification.get_email_deliveries_for_review.return_value = []
    service.project_email_notification.count_deliveries_for_review.return_value = 1
    domain = MagicMock()
    domain.use.return_value.__enter__.return_value = service
    monkeypatch.setitem(check_email_review_queue.__globals__, "DomainService", domain)

    check_email_review_queue()
    assert "project_activity=True" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("state", "offset", "beginning", "end", "expected_error"),
    [
        ("Stable", 10, 0, 10, "active"),
        ("Dead", 9, 0, 10, "undrained"),
        ("Dead", None, 0, 10, "uncommitted"),
        ("Dead", 4, 5, 10, "undrained"),
        ("Dead", 11, 0, 10, "undrained"),
        ("Dead", 10, 0, 10, None),
        ("Dead", None, 0, 0, None),
    ],
)
def test_phoenix_owner_requires_drained_legacy_consumers(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    offset: int | None,
    beginning: int,
    end: int,
    expected_error: str | None,
) -> None:
    admin = Mock()
    consumer = Mock()
    notification = TopicPartition("notification_publish", 0)
    admin.describe_consumer_groups.side_effect = [
        [SimpleNamespace(state=state)],
        [SimpleNamespace(state="Empty")],
    ]
    admin.list_consumer_group_offsets.return_value = (
        {} if offset is None else {notification: OffsetAndMetadata(offset, "", -1)}
    )
    consumer.partitions_for_topic.return_value = {0}
    consumer.beginning_offsets.return_value = {notification: beginning}
    consumer.end_offsets.return_value = {notification: end}
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaConsumer", lambda **_kwargs: consumer)
    monkeypatch.setitem(
        check_legacy_consumers_drained.__globals__,
        "Env",
        SimpleNamespace(PROJECT_NAME="langboard", BROADCAST_URLS=["unused"]),
    )

    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            check_legacy_consumers_drained()
    else:
        check_legacy_consumers_drained()
        assert admin.list_consumer_group_offsets.call_count == 1

    admin.close.assert_called_once()
    consumer.close.assert_called_once()


@pytest.mark.parametrize(
    ("offsets", "expected_error"),
    [
        ({0: 8, 1: 12}, None),
        ({0: 7, 1: 12}, "not caught up"),
        ({0: 8}, "not caught up"),
        ({0: 8, 1: 13}, "not caught up"),
        ({0: 3, 1: 12}, "not caught up"),
    ],
)
def test_phoenix_owner_requires_caught_up_fanout_group(
    monkeypatch: pytest.MonkeyPatch, offsets: dict[int, int], expected_error: str | None
) -> None:
    admin = Mock()
    consumer = Mock()
    admin.describe_consumer_groups.return_value = [SimpleNamespace(state="Stable")]
    partitions = [TopicPartition("socket_publish", partition) for partition in (0, 1)]
    consumer.partitions_for_topic.return_value = {0, 1}
    consumer.beginning_offsets.return_value = {partitions[0]: 4, partitions[1]: 10}
    consumer.end_offsets.return_value = {partitions[0]: 8, partitions[1]: 12}
    admin.list_consumer_group_offsets.return_value = {
        partitions[partition]: OffsetAndMetadata(offset, "", -1) for partition, offset in offsets.items()
    }
    monkeypatch.setenv("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", "phoenix-owner")
    monkeypatch.setitem(check_phoenix_fanout_caught_up.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(check_phoenix_fanout_caught_up.__globals__, "KafkaConsumer", lambda **_kwargs: consumer)
    monkeypatch.setitem(check_phoenix_fanout_caught_up.__globals__, "Env", SimpleNamespace(BROADCAST_URLS=["unused"]))

    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            check_phoenix_fanout_caught_up()
    else:
        check_phoenix_fanout_caught_up()

    admin.close.assert_called_once()
    consumer.close.assert_called_once()


def test_phoenix_owner_requires_configured_fanout_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        check_phoenix_fanout_caught_up()


def test_phoenix_owner_rejects_source_topic_different_from_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", "phoenix-owner")
    monkeypatch.setenv("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC", "socket_publish_canary")
    with pytest.raises(RuntimeError, match="does not match the Python publisher"):
        check_phoenix_fanout_caught_up()


def test_phoenix_owner_rejects_inactive_fanout_group_even_without_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = Mock()
    admin.describe_consumer_groups.return_value = [SimpleNamespace(state="Empty")]
    monkeypatch.setenv("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", "phoenix-owner")
    monkeypatch.setitem(check_phoenix_fanout_caught_up.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(check_phoenix_fanout_caught_up.__globals__, "Env", SimpleNamespace(BROADCAST_URLS=["unused"]))

    with pytest.raises(RuntimeError, match="not active"):
        check_phoenix_fanout_caught_up()
    admin.close.assert_called_once()


def test_phoenix_owner_rejects_active_legacy_notification_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = Mock()
    consumer = Mock()
    admin.describe_consumer_groups.side_effect = [
        [SimpleNamespace(state="Dead")],
        [SimpleNamespace(state="Stable")],
    ]
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaConsumer", lambda **_kwargs: consumer)
    monkeypatch.setitem(
        check_legacy_consumers_drained.__globals__,
        "Env",
        SimpleNamespace(PROJECT_NAME="langboard", BROADCAST_URLS=["unused"]),
    )

    with pytest.raises(RuntimeError, match="Legacy consumer group is active: langboard-notification-node-owner"):
        check_legacy_consumers_drained()

    admin.close.assert_called_once()
    consumer.close.assert_called_once()


@pytest.mark.parametrize("retained_offset", [None, 3])
def test_phoenix_owner_handles_absent_legacy_topic(
    monkeypatch: pytest.MonkeyPatch, retained_offset: int | None
) -> None:
    admin = Mock()
    consumer = Mock()
    notification = TopicPartition("notification_publish", 0)
    admin.describe_consumer_groups.side_effect = [
        [SimpleNamespace(state="Dead")],
        [SimpleNamespace(state="Dead")],
    ]
    admin.list_consumer_group_offsets.return_value = (
        {} if retained_offset is None else {notification: OffsetAndMetadata(retained_offset, "", -1)}
    )
    consumer.partitions_for_topic.return_value = None
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    consumer_factory = Mock(return_value=consumer)
    monkeypatch.setitem(check_legacy_consumers_drained.__globals__, "KafkaConsumer", consumer_factory)
    monkeypatch.setitem(
        check_legacy_consumers_drained.__globals__,
        "Env",
        SimpleNamespace(PROJECT_NAME="langboard", BROADCAST_URLS=["unused"]),
    )

    if retained_offset is None:
        check_legacy_consumers_drained()
    else:
        with pytest.raises(RuntimeError, match="missing with retained offsets"):
            check_legacy_consumers_drained()

    assert consumer_factory.call_args.kwargs["allow_auto_create_topics"] is False
    admin.close.assert_called_once()
    consumer.close.assert_called_once()


@pytest.mark.parametrize("offset", [None, 4, 10])
def test_phoenix_owner_rejects_missing_or_unretained_offsets(
    monkeypatch: pytest.MonkeyPatch, offset: int | None
) -> None:
    admin = Mock()
    consumer = Mock()
    partition = TopicPartition("socket_publish", 0)
    consumer.partitions_for_topic.return_value = {0}
    consumer.beginning_offsets.return_value = {partition: 5}
    consumer.end_offsets.return_value = {partition: 9}
    admin.list_consumer_group_offsets.return_value = (
        {} if offset is None else {partition: OffsetAndMetadata(offset, "", -1)}
    )
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaConsumer", lambda **_kwargs: consumer)
    monkeypatch.setitem(require_existing_group.__globals__, "Env", SimpleNamespace(BROADCAST_URLS=["unused"]))

    with pytest.raises(RuntimeError, match="missing or expired"):
        require_existing_group("phoenix-owner")

    admin.close.assert_called_once()
    consumer.close.assert_called_once()


def test_phoenix_owner_accepts_retained_group_offsets(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = Mock()
    consumer = Mock()
    partition = TopicPartition("socket_publish", 0)
    consumer.partitions_for_topic.return_value = {0}
    consumer.beginning_offsets.return_value = {partition: 5}
    consumer.end_offsets.return_value = {partition: 9}
    admin.list_consumer_group_offsets.return_value = {partition: OffsetAndMetadata(7, "", -1)}
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaConsumer", lambda **_kwargs: consumer)
    monkeypatch.setitem(require_existing_group.__globals__, "Env", SimpleNamespace(BROADCAST_URLS=["unused"]))

    require_existing_group("phoenix-owner")

    admin.close.assert_called_once()
    consumer.close.assert_called_once()


def test_phoenix_owner_closes_admin_when_consumer_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = Mock()
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaAdminClient", lambda **_kwargs: admin)
    monkeypatch.setitem(require_existing_group.__globals__, "KafkaConsumer", Mock(side_effect=OSError("unavailable")))
    monkeypatch.setitem(require_existing_group.__globals__, "Env", SimpleNamespace(BROADCAST_URLS=["unused"]))

    with pytest.raises(OSError, match="unavailable"):
        require_existing_group("phoenix-owner")

    admin.close.assert_called_once()
