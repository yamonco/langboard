import hashlib
import hmac
import json
import os
import pytest
from pydantic import ValidationError


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.schemas.WebhookSchemaApi import webhook_openapi  # noqa: E402
from langboard_shared.tasks.webhooks.utils import WebhookModel  # noqa: E402
from langboard_shared.tasks.webhooks.WebhookTask import _accepts_event, signed_request  # noqa: E402


def test_ready_event_has_stable_cloudevents_mapping_and_signed_body() -> None:
    model = WebhookModel(
        event="io.langboard.work.ready.v1",
        event_id="event-1",
        occurred_at="2026-09-23T11:00:00+00:00",
        data={
            "project_uid": "project-1",
            "card_uid": "card-1",
            "execution_generation": 2,
            "title": "Build feature",
            "labels": ["backend"],
            "assignees": [],
            "direct_blocker_uids": [],
            "card_url": "https://example.com/board/project-1/card-1",
            "source_revision": "revision-2",
        },
    )
    body, headers = signed_request(model, "secret", timestamp=123)
    payload = json.loads(body)
    assert payload["specversion"] == "1.0"
    assert set(payload) == {"specversion", "id", "source", "subject", "type", "time", "data"}
    assert payload["id"] == "event-1"
    assert payload["source"] == "/projects/project-1"
    assert payload["subject"] == "cards/card-1"
    assert payload["type"] == model.event
    assert payload["data"]["execution_generation"] == 2
    assert "project_uid" not in payload["data"]
    assert "card_uid" not in payload["data"]
    assert "semantic_state" not in payload["data"]
    assert headers["X-Langboard-Webhook-Timestamp"] == "123"
    assert headers["X-Langboard-Webhook-Signature"] == "v1=" + hmac.new(
        b"secret", b"123." + body, hashlib.sha256
    ).hexdigest()


def test_work_event_rejects_unexpected_private_fields() -> None:
    model = WebhookModel(
        event="io.langboard.work.ready.v1",
        data={
            "project_uid": "p",
            "card_uid": "c",
            "execution_generation": 1,
            "title": "Task",
            "card_url": "/board/p/c",
            "source_revision": "r",
            "private_note": "do not leak",
        },
    )
    with pytest.raises(ValidationError):
        signed_request(model, None)


def test_work_event_schema_describes_cloudevents_and_array_payload() -> None:
    response = webhook_openapi()
    schema = response.body.decode("utf-8")
    parsed = json.loads(schema)["components"]["schemas"]["io.langboard.work.ready.v1"]
    assert parsed["properties"]["specversion"]["enum"] == ["1.0"]
    assert parsed["properties"]["data"]["properties"]["labels"]["type"] == "array"
    assert parsed["properties"]["data"]["properties"]["execution_generation"]["type"] == "integer"
    assert parsed["properties"]["data"]["properties"]["source_revision"]["format"] == "date-time"
    assert "Card.updated_at" in parsed["properties"]["data"]["properties"]["source_revision"]["description"]
    assert set(parsed["properties"]) == {"specversion", "id", "source", "subject", "type", "time", "data"}
    assert "project_uid" not in parsed["properties"]["data"]["properties"]


def test_execution_events_require_explicit_webhook_opt_in() -> None:
    setting = type("Setting", (), {"events": None})()
    assert not _accepts_event(setting, "io.langboard.work.ready.v1")
    setting.events = ["io.langboard.work.ready.v1"]
    assert _accepts_event(setting, "io.langboard.work.ready.v1")
