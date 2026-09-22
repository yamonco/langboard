import asyncio
import json
import logging
import os
from base64 import b64decode
from hashlib import sha256
from time import monotonic
from urllib.parse import quote
from uuid import uuid4
import websockets
from kafka import KafkaConsumer, KafkaProducer
from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from redis import Redis


SOCKET_TOPIC = os.environ.get("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC", "socket_publish")

logging.getLogger("kafka").setLevel(logging.WARNING)


def _socket_data(user_uid: str, probe_id: str, event: str) -> dict:
    return {
        "data": {"probe_id": probe_id},
        "publish_models": {
            "topic": "user_private",
            "topic_id": user_uid,
            "event": event,
            "data_keys": "probe_id",
        },
    }


def _create_access_token() -> tuple[str, str]:
    user, _subemail = DomainService().user.get_by_email(Env.ADMIN_EMAIL)
    if not user or not user.activated_at:
        raise RuntimeError("The configured administrator must be activated")

    access_token, _refresh_token = AuthSecurity.authenticate(user.id)
    return access_token, user.get_uid()


def _wait_for_assignment(consumer: KafkaConsumer, timeout_seconds: float = 15) -> None:
    deadline = monotonic() + timeout_seconds
    while not consumer.assignment() and monotonic() < deadline:
        consumer.poll(timeout_ms=250)
    if not consumer.assignment():
        raise RuntimeError("Kafka did not assign the dead-letter probe topic")


def _wait_for_dead_letter(
    consumer: KafkaConsumer,
    payload_digest: str,
    timeout_seconds: float = 15,
) -> dict:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        records = consumer.poll(timeout_ms=250)
        for messages in records.values():
            for message in messages:
                if message.value.get("payload_sha256") == payload_digest:
                    return message.value
    raise RuntimeError("Phoenix did not publish the rejected record to the dead-letter topic")


async def _receive_event(websocket, event: str, probe_id: str, timeout_seconds: float = 15) -> dict:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        remaining = deadline - monotonic()
        payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        if not isinstance(payload, str):
            continue

        frame = json.loads(payload)
        if frame.get("event") == event and frame.get("data", {}).get("probe_id") == probe_id:
            return frame
    raise RuntimeError(f"Phoenix did not fan out {event}")


async def _run() -> None:
    socket_url = os.environ["PHOENIX_SOCKET_URL"].rstrip("/")
    dead_letter_topic = os.environ["PHOENIX_SOCKET_DLQ_TOPIC"]
    access_token, user_uid = _create_access_token()
    probe_id = uuid4().hex

    producer = KafkaProducer(
        bootstrap_servers=Env.BROADCAST_URLS,
        acks="all",
        enable_idempotence=True,
        value_serializer=lambda value: json.dumps(value, separators=(",", ":")).encode(),
    )
    dead_letter_consumer = KafkaConsumer(
        dead_letter_topic,
        bootstrap_servers=Env.BROADCAST_URLS,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"{dead_letter_topic}-{probe_id}",
        value_deserializer=lambda value: json.loads(value.decode()),
    )
    cache = Redis.from_url(Env.CACHE_URL)

    try:
        await asyncio.to_thread(_wait_for_assignment, dead_letter_consumer)

        async with websockets.connect(
            f"{socket_url}/?authorization={quote(access_token, safe='')}",
            open_timeout=10,
            close_timeout=5,
            max_size=int(os.environ.get("SOCKET_MAX_PAYLOAD_MB", "8")) * 1024 * 1024,
        ) as websocket:
            inline_event = f"probe:inline:{probe_id}"
            inline_envelope = {
                "schema_version": "2",
                "event_id": str(uuid4()),
                "event": SOCKET_TOPIC,
                "occurred_at": "2026-09-12T12:00:00Z",
                "data": _socket_data(user_uid, probe_id, inline_event),
            }
            producer.send(SOCKET_TOPIC, inline_envelope).get(timeout=10)
            await _receive_event(websocket, inline_event, probe_id)

            legacy_event = f"probe:legacy:{probe_id}"
            cache_key = f"broadcast-phoenix-probe-{probe_id}"
            cache.set(cache_key, json.dumps(_socket_data(user_uid, probe_id, legacy_event)), ex=60)
            producer.send(SOCKET_TOPIC, {"cache_key": cache_key}).get(timeout=10)
            await _receive_event(websocket, legacy_event, probe_id)

            rejected_payload = json.dumps(
                {"cache_key": f"invalid-phoenix-probe-{probe_id}"},
                separators=(",", ":"),
            ).encode()
            producer.send(SOCKET_TOPIC, json.loads(rejected_payload)).get(timeout=10)
            rejected_digest = sha256(rejected_payload).hexdigest()

            dead_letter = await asyncio.to_thread(
                _wait_for_dead_letter,
                dead_letter_consumer,
                rejected_digest,
            )
            assert dead_letter["reason"] == "invalid_broker_envelope"
            assert b64decode(dead_letter["payload_base64"]) == rejected_payload
            assert dead_letter["source"]["topic"] == SOCKET_TOPIC
    finally:
        cache.delete(f"broadcast-phoenix-probe-{probe_id}")
        dead_letter_consumer.close()
        producer.close()

    print("Phoenix Kafka ingress probe passed")


if __name__ == "__main__":
    asyncio.run(_run())
