# ruff: noqa: F811
"""Explicit executor uses exact signed HTTP bytes and current post-DNS fences."""

import hashlib
import hmac
import importlib
import json
import httpx
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppExecutionOutbox
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.tasks.webhooks.utils import ResolvedWebhookTarget
from test_app_event_delivery import delivery_scope


worker = importlib.import_module("langboard_shared.tasks.webhooks.AppEventDeliveryWorker")
webhook = importlib.import_module("langboard_shared.tasks.webhooks.WebhookTask")


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("status", [200, 503, 302])
async def test_exact_http_bytes_success_failure_and_redirect_denial(board, monkeypatch, status):
    _, _, event = delivery_scope(board, monkeypatch)
    seen = []

    async def resolve(url):
        assert url == "https://app.example/events"
        return ResolvedWebhookTarget("https://203.0.113.1/events", "app.example", "app.example")

    def receive(request):
        seen.append(request)
        timestamp = request.headers["X-Langboard-Webhook-Timestamp"]
        signature = hmac.new(
            b"test-signing-secret", timestamp.encode() + b"." + request.content, hashlib.sha256
        ).hexdigest()
        assert request.headers["X-Langboard-Webhook-Signature"] == "v1=" + signature
        assert request.headers["host"] == "app.example"
        assert request.extensions["sni_hostname"] == "app.example"
        payload = json.loads(request.content)
        assert payload["event_uid"] == event.get_uid() and payload["started"] is False
        return httpx.Response(status, headers={"Location": "https://other.example/events"})

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"].read == 60
        return original(transport=httpx.MockTransport(receive), **kwargs)

    monkeypatch.setattr(worker, "ensure_public_webhook_url", resolve)
    monkeypatch.setattr(webhook, "AsyncClient", client)
    if status == 200:
        result = await worker.deliver_app_event(event.id, 1)
        assert result["state"] == "delivered" and result["started"] is False
    else:
        with pytest.raises(worker.AppEventDeliveryFailed):
            await worker.deliver_app_event(event.id, 1)
    assert len(seen) == 1
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == ("delivered" if status == 200 else "pending")
        assert row.attempt_count == 1 and row.claim_token is None


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("change", ["connection", "destination", "private_dns"])
async def test_dns_and_post_dns_revocation_prevent_http(board, monkeypatch, change):
    connection, setting, event = delivery_scope(board, monkeypatch)

    async def resolve(url):
        if change == "private_dns":
            raise ValueError("Webhook URL resolved to a private network")
        with DbSession.atomic() as db:
            if change == "connection":
                connection.state = "revoked"
                db.update(connection)
            else:
                setting.url = "https://app.example/new-events"
                db.update(setting)
        return ResolvedWebhookTarget("https://203.0.113.1/events", "app.example", "app.example")

    monkeypatch.setattr(worker, "ensure_public_webhook_url", resolve)
    monkeypatch.setattr(webhook, "AsyncClient", lambda **_: pytest.fail("Forbidden event must not reach HTTP"))
    if change == "private_dns":
        with pytest.raises(worker.AppEventDeliveryFailed):
            await worker.deliver_app_event(event.id, 1)
    else:
        assert await worker.deliver_app_event(event.id, 1) is None
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == ("pending" if change == "private_dns" else "blocked")
        assert row.claim_token is None


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
async def test_response_after_lease_expiry_cannot_mark_delivered(board, monkeypatch):
    from datetime import timedelta
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.services.AppGovernance import AppGovernanceConflict

    _, _, event = delivery_scope(board, monkeypatch)

    async def resolve(url):
        return ResolvedWebhookTarget("https://203.0.113.1/events", "app.example", "app.example")

    async def late_response(*args, **kwargs):
        with DbSession.atomic() as db:
            row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
            row.lease_until = SafeDateTime.now() - timedelta(seconds=1)
            db.update(row)

    monkeypatch.setattr(worker, "ensure_public_webhook_url", resolve)
    monkeypatch.setattr(worker, "post_resolved_webhook_bytes", late_response)
    with pytest.raises(AppGovernanceConflict):
        await worker.deliver_app_event(event.id, 1)
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == "delivering"
        assert row.delivery_history[-1]["outcome"] == "claimed"
