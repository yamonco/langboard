import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import quote
from uuid import uuid4
import websockets
from kafka import KafkaProducer
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env


SOCKET_TOPIC = os.environ.get("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC", "socket_publish")
CONNECT_TIMEOUT_SECONDS = 10
RECONNECT_TIMEOUT_SECONDS = 90

logging.getLogger("kafka").setLevel(logging.WARNING)


def _create_access_token() -> tuple[str, str]:
    user, _subemail = DomainService().user.get_by_email(Env.ADMIN_EMAIL)
    if not user or not user.activated_at:
        raise RuntimeError("The configured administrator must be activated")

    access_token, _refresh_token = AuthSecurity.authenticate(user.id)
    return access_token, user.get_uid()


def _socket_data(user_uid: str, event: str, probe_id: str) -> dict:
    return {
        "data": {"probe_id": probe_id},
        "publish_models": {
            "topic": "user_private",
            "topic_id": user_uid,
            "event": event,
            "data_keys": "probe_id",
        },
    }


def _publish(producer: KafkaProducer, event: str, user_uid: str, probe_id: str) -> set[str]:
    partitions = producer.partitions_for(SOCKET_TOPIC)
    if not partitions:
        raise RuntimeError("Kafka returned no partitions for the fanout topic")

    expected = set()
    for partition in sorted(partitions):
        partition_probe_id = f"{probe_id}:{partition}"
        producer.send(
            SOCKET_TOPIC,
            {
                "schema_version": "2",
                "event_id": str(uuid4()),
                "event": SOCKET_TOPIC,
                "occurred_at": datetime.now(UTC).isoformat(),
                "data": _socket_data(user_uid, event, partition_probe_id),
            },
            partition=partition,
        ).get(timeout=10)
        expected.add(partition_probe_id)
    return expected


async def _receive_event(websocket, event: str, expected: set[str], timeout_seconds: float) -> None:
    deadline = monotonic() + timeout_seconds
    pending = expected.copy()
    while pending and monotonic() < deadline:
        payload = await asyncio.wait_for(websocket.recv(), timeout=max(deadline - monotonic(), 0.1))
        if not isinstance(payload, str):
            continue

        frame = json.loads(payload)
        if frame.get("event") == event:
            pending.discard(frame.get("data", {}).get("probe_id"))

    if pending:
        raise RuntimeError(f"Phoenix did not fan out {event} from partitions: {sorted(pending)}")
    print(f"Phoenix received {event} from all {len(expected)} partitions", flush=True)


async def _connect(url: str, access_token: str):
    return await websockets.connect(
        f"{url.rstrip('/')}/?authorization={quote(access_token, safe='')}",
        open_timeout=CONNECT_TIMEOUT_SECONDS,
        close_timeout=5,
        max_size=int(os.environ.get("SOCKET_MAX_PAYLOAD_MB", "8")) * 1024 * 1024,
    )


async def _wait_for_disconnect(websocket) -> None:
    try:
        while True:
            await websocket.recv()
    except websockets.ConnectionClosed:
        return


async def _reconnect(urls: list[str], access_token: str):
    deadline = monotonic() + RECONNECT_TIMEOUT_SECONDS
    while monotonic() < deadline:
        for url in urls:
            try:
                return await _connect(url, access_token)
            except (OSError, TimeoutError, websockets.WebSocketException):
                continue
        await asyncio.sleep(1)

    raise RuntimeError("Phoenix client did not reconnect before the timeout")


async def _run() -> None:
    urls = [url.strip() for url in os.environ["PHOENIX_SOCKET_URLS"].split(",") if url.strip()]
    if len(urls) < 2:
        raise ValueError("PHOENIX_SOCKET_URLS must contain the ingress and failover URLs")

    access_token, user_uid = _create_access_token()
    probe_id = uuid4().hex
    initial_event = f"probe:cluster:initial:{probe_id}"
    reconnected_event = f"probe:cluster:reconnected:{probe_id}"
    producer = KafkaProducer(
        bootstrap_servers=Env.BROADCAST_URLS,
        acks="all",
        enable_idempotence=True,
        value_serializer=lambda value: json.dumps(value, separators=(",", ":")).encode(),
    )

    try:
        websocket = await _connect(urls[0], access_token)
        print("Phoenix reconnect probe connected", flush=True)
        try:
            expected = _publish(producer, initial_event, user_uid, probe_id)
            await _receive_event(websocket, initial_event, expected, CONNECT_TIMEOUT_SECONDS)
            print("Phoenix reconnect probe received initial event", flush=True)
            await _wait_for_disconnect(websocket)
        finally:
            await websocket.close()

        print("Phoenix reconnect probe detected disconnect", flush=True)
        websocket = await _reconnect([urls[1]], access_token)
        try:
            print("Phoenix reconnect probe reconnected to failover", flush=True)
            expected = _publish(producer, reconnected_event, user_uid, probe_id)
            await _receive_event(websocket, reconnected_event, expected, CONNECT_TIMEOUT_SECONDS)
        finally:
            await websocket.close()

        websocket = await _reconnect([urls[0]], access_token)
        try:
            print("Phoenix reconnect probe reconnected to primary", flush=True)
            restored_event = f"probe:cluster:restored:{probe_id}"
            expected = _publish(producer, restored_event, user_uid, probe_id)
            await _receive_event(websocket, restored_event, expected, CONNECT_TIMEOUT_SECONDS)
        finally:
            await websocket.close()
    finally:
        producer.close()

    print("Phoenix cluster reconnect probe passed", flush=True)


if __name__ == "__main__":
    asyncio.run(_run())
