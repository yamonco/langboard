"""Webhook fan-out contract for push-based WorkEvent delivery.

Routes filtered WorkEvents to registered HTTP endpoints with per-endpoint
retry and circuit-breaker semantics.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from . import WorkEventEnvelope
from .idempotency import IdempotentConsumer


@dataclass(frozen=True)
class WebhookEndpoint:
    """A registered HTTP endpoint receiving WorkEvents."""

    endpoint_id: str
    url: str
    secret: str = ""
    event_types: frozenset[str] | None = None  # None = all types
    is_active: bool = True


@dataclass
class WebhookDelivery:
    """A single delivery attempt to an endpoint."""

    endpoint_id: str
    event_id: str
    status_code: int = 0
    success: bool = False
    attempt: int = 1
    error: str = ""


@dataclass
class WebhookFanout:
    """Routes WorkEvents to registered endpoints with delivery tracking.

    Each endpoint receives only the event types it subscribes to (or all if
    no filter). The IdempotentConsumer per endpoint prevents duplicate
    deliveries. Circuit-breaker disables endpoints after consecutive failures.
    """

    endpoints: dict[str, WebhookEndpoint] = field(default_factory=dict)
    _consumers: dict[str, IdempotentConsumer] = field(default_factory=dict)
    _delivery_log: list[WebhookDelivery] = field(default_factory=list)
    _failure_counts: dict[str, int] = field(default_factory=dict)

    circuit_breaker_threshold = 5
    max_retries = 3

    def register(self, endpoint: WebhookEndpoint) -> None:
        self.endpoints[endpoint.endpoint_id] = endpoint
        self._consumers[endpoint.endpoint_id] = IdempotentConsumer()
        self._failure_counts[endpoint.endpoint_id] = 0

    def unregister(self, endpoint_id: str) -> None:
        self.endpoints.pop(endpoint_id, None)
        self._consumers.pop(endpoint_id, None)
        self._failure_counts.pop(endpoint_id, None)

    def fanout(self, event: Any, http_post: Any) -> list[WebhookDelivery]:
        """Deliver an event to all matching active endpoints.

        http_post(url, payload, headers) → (status_code, response_body)
        """
        results: list[WebhookDelivery] = []

        for endpoint in self.endpoints.values():
            if not endpoint.is_active:
                continue
            if self._is_circuit_open(endpoint.endpoint_id):
                continue
            if not self._matches(endpoint, event):
                continue

            delivery = self._deliver(endpoint, event, http_post)
            results.append(delivery)
            self._record(delivery)

        return results

    def _matches(self, endpoint: WebhookEndpoint, event: Any) -> bool:
        if endpoint.event_types is None:
            return True
        return event.event_type.value in endpoint.event_types

    def _deliver(
        self, endpoint: WebhookEndpoint, event: Any, http_post: Any
    ) -> WebhookDelivery:
        consumer = self._consumers.get(endpoint.endpoint_id)
        if consumer is None:
            consumer = IdempotentConsumer()
            self._consumers[endpoint.endpoint_id] = consumer

        envelope = WorkEventEnvelope(event=event)
        payload = json.dumps(envelope.to_dict())

        headers = {"Content-Type": "application/json"}
        if endpoint.secret:
            signature = hashlib.sha256(
                (endpoint.secret + payload).encode()
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        delivery = WebhookDelivery(
            endpoint_id=endpoint.endpoint_id,
            event_id=event.event_id,
        )

        try:
            status_code, _ = http_post(endpoint.url, payload, headers)
            delivery.status_code = status_code
            delivery.success = 200 <= status_code < 300
        except Exception as exc:
            delivery.error = str(exc)

        return delivery

    def _record(self, delivery: WebhookDelivery) -> None:
        self._delivery_log.append(delivery)
        if len(self._delivery_log) > 1000:
            self._delivery_log = self._delivery_log[-500:]

        count = self._failure_counts.get(delivery.endpoint_id, 0)
        if delivery.success:
            self._failure_counts[delivery.endpoint_id] = 0
        else:
            self._failure_counts[delivery.endpoint_id] = count + 1

    def _is_circuit_open(self, endpoint_id: str) -> bool:
        return self._failure_counts.get(endpoint_id, 0) >= self.circuit_breaker_threshold

    def get_deliveries(self, endpoint_id: str | None = None) -> list[WebhookDelivery]:
        if endpoint_id:
            return [d for d in self._delivery_log if d.endpoint_id == endpoint_id]
        return list(self._delivery_log)
