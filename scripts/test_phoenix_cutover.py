import runpy
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Callable, cast
from unittest.mock import Mock
import pytest
from kafka.structs import OffsetAndMetadata, TopicPartition


_gate = runpy.run_path(str(Path(__file__).with_name("check-phoenix-cutover.py")))
_bootstrap = runpy.run_path(str(Path(__file__).with_name("bootstrap-phoenix-kafka-group.py")))
check_consumer_group_stopped = cast(Callable[[Mock, str, str, str], str], _gate["check_consumer_group_stopped"])
check_consumer_group_drained = cast(
    Callable[[Mock, Mock, str, str, str, str], None], _gate["check_consumer_group_drained"]
)
require_existing_group = cast(FunctionType, _bootstrap["require_existing_group"])


def test_stopped_fanout_does_not_need_to_follow_new_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROADCAST_NODE_FANOUT_CONSUMER_GROUP", raising=False)
    admin = Mock()
    admin.describe_consumer_groups.return_value = [SimpleNamespace(state="Dead")]

    group_id = check_consumer_group_stopped(
        admin, "Node fanout", "BROADCAST_NODE_FANOUT_CONSUMER_GROUP", "socket-node-fanout"
    )

    assert group_id.endswith("-socket-node-fanout")
    admin.list_consumer_group_offsets.assert_not_called()


def test_active_fanout_still_blocks_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROADCAST_NODE_FANOUT_CONSUMER_GROUP", raising=False)
    admin = Mock()
    admin.describe_consumer_groups.return_value = [SimpleNamespace(state="Stable")]

    with pytest.raises(RuntimeError, match="still active"):
        check_consumer_group_stopped(admin, "Node fanout", "BROADCAST_NODE_FANOUT_CONSUMER_GROUP", "socket-node-fanout")


def test_notification_side_effect_must_be_drained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP", raising=False)
    admin = Mock()
    admin.describe_consumer_groups.return_value = [SimpleNamespace(state="Dead")]
    consumer = Mock()
    consumer.partitions_for_topic.return_value = {0}
    partition = TopicPartition("notification_publish", 0)
    consumer.beginning_offsets.return_value = {partition: 0}
    consumer.end_offsets.return_value = {partition: 2}
    admin.list_consumer_group_offsets.return_value = {partition: OffsetAndMetadata(1, "", -1)}

    with pytest.raises(RuntimeError, match="not drained"):
        check_consumer_group_drained(
            admin,
            consumer,
            "Node notification side effect",
            "BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP",
            "notification_publish",
            "notification-node-owner",
        )


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
