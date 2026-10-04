import runpy
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Callable, cast
from unittest.mock import MagicMock, Mock
import pytest
from kafka.structs import OffsetAndMetadata, TopicPartition


_scripts = Path(__file__).resolve().parents[4] / "scripts"
_gate = runpy.run_path(str(_scripts / "check-phoenix-cutover.py"))
_bootstrap = runpy.run_path(str(_scripts / "bootstrap-phoenix-kafka-group.py"))
check_required_celery_tasks = cast(Callable[[], None], _gate["check_required_celery_tasks"])
check_email_delivery_owner = cast(Callable[[], None], _gate["check_email_delivery_owner"])
check_legacy_consumers_drained = cast(Callable[[], None], _gate["check_legacy_consumers_drained"])
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


def test_phoenix_owner_requires_reachable_smtp_server(monkeypatch: pytest.MonkeyPatch) -> None:
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
    connection = MagicMock()
    create_connection = Mock(return_value=connection)
    monkeypatch.setattr(check_email_delivery_owner.__globals__["socket"], "create_connection", create_connection)

    check_email_delivery_owner()
    create_connection.assert_called_once_with((env.MAIL_SERVER, env.MAIL_PORT), timeout=3)

    create_connection.side_effect = ConnectionRefusedError()
    with pytest.raises(RuntimeError, match="SMTP server is unreachable"):
        check_email_delivery_owner()


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
