import os
from datetime import datetime, timezone
from unittest.mock import Mock


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts import (  # noqa: E402
    WorkEvent,
    WorkEventActor,
    WorkEventScope,
    WorkEventType,
)
from langboard_shared.domain.contracts.webhook_fanout import (  # noqa: E402
    WebhookEndpoint,
    WebhookFanout,
)


def make_event(etype: WorkEventType = WorkEventType.CARD_ASSIGNED) -> WorkEvent:
    return WorkEvent(
        event_id="evt-test-1",
        event_type=etype,
        actor=WorkEventActor(principal_type="user", principal_id="u1", display_name="T"),
        scope_type=WorkEventScope.CARD,
        scope_id="c1",
        project_uid="p1",
        occurred_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )


def make_fanout() -> WebhookFanout:
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(endpoint_id="ep1", url="https://a.example.com/hook"))
    fanout.register(WebhookEndpoint(endpoint_id="ep2", url="https://b.example.com/hook"))
    return fanout


def test_fanout_delivers_to_all_active_endpoints():
    fanout = make_fanout()
    mock_post = Mock(return_value=(200, "ok"))
    results = fanout.fanout(make_event(), mock_post)
    assert len(results) == 2
    assert all(r.success for r in results)
    assert mock_post.call_count == 2


def test_fanout_respects_event_type_filter():
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(
        endpoint_id="ep-assign",
        url="https://a.example.com/hook",
        event_types=frozenset({"card.assigned"}),
    ))
    fanout.register(WebhookEndpoint(
        endpoint_id="ep-mention",
        url="https://b.example.com/hook",
        event_types=frozenset({"card.mentioned"}),
    ))
    mock_post = Mock(return_value=(200, "ok"))
    results = fanout.fanout(make_event(WorkEventType.CARD_ASSIGNED), mock_post)
    assert len(results) == 1
    assert results[0].endpoint_id == "ep-assign"


def test_fanout_skips_inactive_endpoints():
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(endpoint_id="ep1", url="https://a.com", is_active=False))
    mock_post = Mock(return_value=(200, "ok"))
    results = fanout.fanout(make_event(), mock_post)
    assert len(results) == 0


def test_failed_delivery_records_error():
    fanout = make_fanout()
    mock_post = Mock(side_effect=ConnectionError("refused"))
    results = fanout.fanout(make_event(), mock_post)
    assert all(not r.success for r in results)
    assert all(r.error == "refused" for r in results)


def test_circuit_breaker_opens_after_threshold():
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(endpoint_id="ep1", url="https://a.com"))
    fanout.circuit_breaker_threshold = 3
    mock_post = Mock(side_effect=ConnectionError("refused"))

    for _ in range(3):
        fanout.fanout(make_event(), mock_post)

    assert fanout._is_circuit_open("ep1")
    # Next fanout should skip this endpoint
    results = fanout.fanout(make_event(), mock_post)
    assert len(results) == 0


def test_circuit_resets_on_success():
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(endpoint_id="ep1", url="https://a.com"))
    fanout.circuit_breaker_threshold = 2

    fail_post = Mock(side_effect=ConnectionError("refused"))
    fanout.fanout(make_event(), fail_post)
    fanout.fanout(make_event(), fail_post)
    assert fanout._is_circuit_open("ep1")

    # Manually reset by recording a success
    fanout._failure_counts["ep1"] = 0
    assert not fanout._is_circuit_open("ep1")


def test_signature_header_included_when_secret_set():
    fanout = WebhookFanout()
    fanout.register(WebhookEndpoint(endpoint_id="ep1", url="https://a.com", secret="mysecret"))
    mock_post = Mock(return_value=(200, "ok"))
    fanout.fanout(make_event(), mock_post)
    call_args = mock_post.call_args
    headers = call_args[0][2]
    assert "X-Webhook-Signature" in headers
    assert headers["X-Webhook-Signature"].startswith("sha256=")
