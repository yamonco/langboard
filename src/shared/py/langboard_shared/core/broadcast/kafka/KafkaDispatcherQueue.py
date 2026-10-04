import json
from typing import Any
from kafka import KafkaProducer
from ....Env import Env
from ..BaseDispatcherQueue import BaseDispatcherQueue
from ..DispatcherModel import DispatcherEnvelope, DispatcherModel


def _serialize_message(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class KafkaDispatcherQueue(BaseDispatcherQueue):
    def __init__(self):
        self.producer: KafkaProducer | None = None

    def put(self, event: str | DispatcherModel, data: dict[str, Any] | None = None):
        if not self.producer:
            self.producer = KafkaProducer(
                bootstrap_servers=Env.BROADCAST_URLS,
                enable_idempotence=True,
                max_request_size=Env.BROADCAST_MAX_MESSAGE_BYTES,
                value_serializer=_serialize_message,
            )
        model = DispatcherModel(event=event, data=data or {}) if isinstance(event, str) else event
        envelope = DispatcherEnvelope(
            event=model.event,
            data=model.model_dump(mode="json")["data"],
        )
        envelope_data = envelope.model_dump(mode="json")
        if len(_serialize_message(envelope_data)) > Env.BROADCAST_MAX_MESSAGE_BYTES:
            raise ValueError(f"Broadcast payload exceeds the {Env.BROADCAST_MAX_MESSAGE_BYTES} byte limit")
        self.producer.send(model.event, envelope_data).get(timeout=Env.BROADCAST_PUBLISH_TIMEOUT_SECONDS)
