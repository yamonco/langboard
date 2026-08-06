import hashlib
import hmac
import importlib
import json
import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.tasks.webhooks import WebhookTask  # noqa: E402
from langboard_shared.tasks.webhooks.utils import WebhookModel  # noqa: E402


app_setting_module = importlib.import_module("langboard_shared.domain.services.factory.AppSettingService")
webhook_schema_module = importlib.import_module("langboard.routes.schemas.WebhookSchemaApi")


def test_signed_request_has_stable_versioned_envelope() -> None:
    """Retries retain event identity while delivery timestamps remain signed."""

    model = WebhookModel(
        event_id="event-1",
        occurred_at="2026-08-06T07:00:00+00:00",
        event="card_moved",
        data={
            "project_uid": "project-1",
            "card_uid": "card-1",
            "related_cards": [{"card_uid": "other", "title": "private title"}],
            "executor": {
                "uid": "user-1",
                "type": "user",
                "email": "private@example.com",
            },
        },
    )

    body, headers = WebhookTask.signed_request(model, "secret", timestamp=1_786_003_200)
    payload = json.loads(body)

    assert payload == {
        "schema_version": "1",
        "event_id": "event-1",
        "occurred_at": "2026-08-06T07:00:00+00:00",
        "event": "card_moved",
        "data": {
            "project_uid": "project-1",
            "card_uid": "card-1",
            "executor": {"uid": "user-1", "type": "user"},
        },
    }
    assert headers["X-Langboard-Webhook-Id"] == "event-1"
    assert headers["X-Langboard-Webhook-Timestamp"] == "1786003200"
    expected = hmac.new(
        b"secret",
        b"1786003200." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Langboard-Webhook-Signature"] == f"v1={expected}"


def test_legacy_webhook_without_secret_remains_unsigned() -> None:
    """Existing rows remain deliverable while new rows receive signing secrets."""

    _, headers = WebhookTask.signed_request(
        WebhookModel(event="card_created", data={}),
        None,
        timestamp=1_786_003_200,
    )

    assert "X-Langboard-Webhook-Signature" not in headers


def test_webhook_schema_documents_envelope_and_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing schema endpoint is the SSOT for generic consumers."""

    monkeypatch.setattr(
        webhook_schema_module.Broker,
        "get_schema",
        lambda group: {
            "card_created": {
                "project_uid": "string",
                "card_uid": "string",
                "related_cards": {"title": "string"},
                "executor": {"email": "string", "uid": "string"},
            }
        },
    )

    response = webhook_schema_module.webhook_openapi()
    document = json.loads(response.body)
    schema = document["components"]["schemas"]["card_created"]

    assert schema["required"] == [
        "schema_version",
        "event_id",
        "occurred_at",
        "event",
        "data",
    ]
    assert document["x-langboard-webhook-signature"]["algorithm"] == "HMAC-SHA256"
    data_properties = schema["properties"]["data"]["properties"]
    assert set(data_properties) == {"project_uid", "card_uid", "executor"}
    assert set(data_properties["executor"]["properties"]) == {"uid", "type"}


def test_create_webhook_returns_vault_secret_and_cleans_up_on_insert_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The database stores only a secret reference and failed writes leave no key."""

    created: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(app_setting_module.KeyVault, "create_key", lambda key: created.append(key) or "revealed")
    monkeypatch.setattr(app_setting_module.KeyVault, "delete_key", deleted.append)
    monkeypatch.setattr(app_setting_module.AppSettingPublisher, "webhook_setting_created", lambda setting: None)
    service = SimpleNamespace(repo=SimpleNamespace(webhook_setting=SimpleNamespace(insert=lambda setting: None)))

    setting, secret = app_setting_module.AppSettingService.create_webhook_setting(
        service,
        "Hermes",
        " https://example.invalid/hook ",
    )

    assert secret == "revealed"
    assert setting.url == "https://example.invalid/hook"
    assert setting.secret_id == created[0]
    assert "secret_id" not in setting.api_response()
    assert deleted == []

    service.repo.webhook_setting.insert = lambda setting: (_ for _ in ()).throw(RuntimeError("db"))
    with pytest.raises(RuntimeError, match="db"):
        app_setting_module.AppSettingService.create_webhook_setting(
            service,
            "Hermes",
            "https://example.invalid/hook",
        )
    assert deleted == [created[1]]


@pytest.mark.asyncio
async def test_delivery_failure_is_bounded_and_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transport failures surface to Celery without logging response bodies."""

    setting = SimpleNamespace(
        secret_id="secret-id",
        url="https://example.invalid/hook",
        get_uid=lambda: "webhook-1",
    )
    observed_timeout: list[object] = []

    class FakeClient:
        def __init__(self, *, timeout: object) -> None:
            observed_timeout.append(timeout)

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise TimeoutError("bounded")

    monkeypatch.setattr(WebhookTask, "_get_webhook_settings", lambda: [setting])
    monkeypatch.setattr(WebhookTask, "AsyncClient", FakeClient)
    monkeypatch.setattr(WebhookTask.KeyVault, "get_key", lambda key: "secret")

    with pytest.raises(WebhookTask.WebhookDeliveryError, match="1 webhook"):
        await WebhookTask.run_webhook(WebhookModel(event="card_created", data={}))

    assert observed_timeout == [WebhookTask.WEBHOOK_TIMEOUT]
