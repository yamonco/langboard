import hashlib
import hmac
import importlib
import json
import os
from types import SimpleNamespace
import pytest
from pydantic import ValidationError


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.broker import Broker  # noqa: E402
from langboard_shared.tasks.bots.utils.BotTaskDataHelper import BotTaskDataHelper  # noqa: E402
from langboard_shared.tasks.webhooks import WebhookTask  # noqa: E402
from langboard_shared.tasks.webhooks.utils import WEBHOOK_EVENT_NAMES, WebhookModel  # noqa: E402


app_setting_module = importlib.import_module("langboard_shared.domain.services.factory.AppSettingService")
webhook_schema_module = importlib.import_module("langboard.routes.schemas.WebhookSchemaApi")
settings_form_module = importlib.import_module("langboard.routes.settings.Form")


def test_signed_request_has_stable_versioned_envelope() -> None:
    """Retries retain event identity while delivery timestamps remain signed."""

    model = WebhookModel(
        event_id="event-1",
        occurred_at="2026-08-06T07:00:00+00:00",
        event="card_moved",
        data={
            "project_uid": "project-1",
            "project_title": "산모피아",
            "card_uid": "card-1",
            "card_title": "업무 요청사항(2026.08.06)",
            "project_column_uid": "column-2",
            "project_column_name": "진행중",
            "project_column_is_archive": False,
            "old_project_column_uid": "column-1",
            "old_project_column_name": "진행예정",
            "old_project_column_is_archive": False,
            "related_cards": [{"card_uid": "other", "title": "private title"}],
            "executor": {
                "uid": "user-1",
                "type": "user",
                "firstname": "이대중",
                "lastname": "",
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
            "project_title": "산모피아",
            "card_uid": "card-1",
            "card_title": "업무 요청사항(2026.08.06)",
            "project_column_uid": "column-2",
            "project_column_name": "진행중",
            "project_column_is_archive": False,
            "old_project_column_uid": "column-1",
            "old_project_column_name": "진행예정",
            "old_project_column_is_archive": False,
            "executor": {"uid": "user-1", "type": "user", "display_name": "이대중"},
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


def test_retry_keeps_envelope_stable_and_refreshes_signed_delivery_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each endpoint attempt re-signs the same event envelope with a fresh timestamp."""

    timestamps = iter((1_786_003_200, 1_786_003_201))
    monkeypatch.setattr(WebhookTask, "time", lambda: next(timestamps))
    model = WebhookModel(
        event_id="event-1",
        occurred_at="2026-08-06T07:00:00+00:00",
        event="card_created",
        data={"project_uid": "project-1"},
    )

    first_body, first_headers = WebhookTask.signed_request(model, "secret")
    second_body, second_headers = WebhookTask.signed_request(model, "secret")

    assert first_body == second_body
    assert first_headers["X-Langboard-Webhook-Id"] == second_headers["X-Langboard-Webhook-Id"] == "event-1"
    assert first_headers["X-Langboard-Webhook-Timestamp"] == "1786003200"
    assert second_headers["X-Langboard-Webhook-Timestamp"] == "1786003201"
    assert first_headers["X-Langboard-Webhook-Signature"] != second_headers["X-Langboard-Webhook-Signature"]


def test_webhook_event_allowlist_validation_and_omission_compatibility() -> None:
    """Omission and null mean all events; supplied lists are exact non-empty sets."""

    create_form = settings_form_module.CreateWebhookForm(name="Hook", url="https://example.invalid")
    update_form = settings_form_module.UpdateWebhookForm(events=None)
    assert create_form.events is None
    assert "events" not in create_form.model_fields_set
    assert update_form.events is None
    assert "events" in update_form.model_fields_set

    valid = settings_form_module.CreateWebhookForm(
        name="Hook",
        url="https://example.invalid",
        events=["card_created", "card_moved"],
    )
    assert valid.events == ["card_created", "card_moved"]

    for events in ([], ["card_created", "card_created"], ["not_emitted"]):
        with pytest.raises(ValidationError):
            settings_form_module.CreateWebhookForm(
                name="Hook",
                url="https://example.invalid",
                events=events,
            )


def test_webhook_schema_documents_envelope_and_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing schema endpoint is the SSOT for generic consumers."""

    monkeypatch.setattr(
        webhook_schema_module.Broker,
        "get_schema",
        lambda group: {
            "card_created": {
                "project_uid": "string",
                "project_title": "string",
                "card_uid": "string",
                "card_title": "string",
                "project_column_name": "string",
                "project_column_is_archive": "boolean",
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
    assert set(data_properties) == {
        "project_uid",
        "project_title",
        "card_uid",
        "card_title",
        "project_column_name",
        "project_column_is_archive",
        "executor",
    }
    assert set(data_properties["executor"]["properties"]) == {"uid", "type", "display_name"}


def test_minimal_event_data_freezes_safe_bot_and_unknown_actor_labels() -> None:
    """Presentation snapshots exclude credentials while retaining one actor label."""

    assert WebhookTask.minimal_event_data(
        {"executor": {"uid": "bot-1", "type": "bot", "name": "자동화", "api_key": "secret"}}
    ) == {"executor": {"uid": "bot-1", "type": "bot", "display_name": "자동화"}}
    assert WebhookTask.minimal_event_data(
        {"executor": {"uid": "external-1", "type": "external", "email": "private@example.com"}}
    ) == {"executor": {"uid": "external-1", "type": "external", "display_name": "알 수 없음"}}


def test_native_card_snapshot_is_frozen_at_event_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native helper data carries the names needed after later provider changes."""

    actor = SimpleNamespace(api_response=lambda: {"uid": "user-1", "type": "user"})
    project = SimpleNamespace(get_uid=lambda: "project-1", title="산모피아", id=1)
    column = SimpleNamespace(get_uid=lambda: "column-1", name="진행중", is_archive=False)
    card = SimpleNamespace(get_uid=lambda: "card-1", title="업무 요청", project_column_id=1)
    monkeypatch.setattr(
        BotTaskDataHelper,
        "create_card_relationship_context",
        lambda _card: {"parents": [], "children": []},
    )

    data = BotTaskDataHelper.create_card(actor, project, card, column)

    assert data["project_title"] == "산모피아"
    assert data["project_column_name"] == "진행중"
    assert data["project_column_is_archive"] is False
    assert data["card_title"] == "업무 요청"


def test_native_card_move_schema_documents_old_column_snapshot() -> None:
    """The emitted old-column snapshot remains visible to webhook consumers."""

    importlib.import_module("langboard_shared.tasks.bots.CardBotTask")
    schema = Broker.get_schema("webhook")["card_moved"]

    assert schema["old_project_column_uid"] == "string"
    assert schema["old_project_column_name"] == "string"
    assert schema["old_project_column_is_archive"] == "boolean"


def test_webhook_schema_matches_emitted_registry_without_import_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default bot events remain documented even when no task populated the schema file."""

    monkeypatch.setattr(webhook_schema_module.Broker, "get_schema", lambda group: {})

    response = webhook_schema_module.webhook_openapi()
    schemas = json.loads(response.body)["components"]["schemas"]

    assert set(schemas) == WEBHOOK_EVENT_NAMES
    bot_created = schemas["bot_created"]["properties"]["data"]
    assert set(bot_created["properties"]) == {"executor"}
    assert "project_uid" not in bot_created["properties"]

    bot_cron = schemas["bot_cron_scheduled"]["properties"]["data"]
    assert set(bot_cron["properties"]) == {"project_uid", "project_column_uid", "card_uid"}
    assert bot_cron["required"] == ["project_uid", "project_column_uid"]


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

    with pytest.raises(ValueError, match="at least one"):
        app_setting_module.AppSettingService.create_webhook_setting(
            service,
            "Invalid",
            "https://example.invalid/hook",
            [],
        )
    assert created == []

    setting, secret = app_setting_module.AppSettingService.create_webhook_setting(
        service,
        "Hermes",
        " https://example.invalid/hook ",
    )

    assert secret == "revealed"
    assert setting.url == "https://example.invalid/hook"
    assert setting.secret_id == created[0]
    assert setting.events is None
    assert setting.api_response()["events"] is None
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


def test_update_webhook_distinguishes_omitted_events_from_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An omitted field preserves the allowlist while null restores all events."""

    setting = SimpleNamespace(
        name="Hook",
        url="https://example.invalid/hook",
        events=["card_created"],
        has_changes=lambda: True,
        get_uid=lambda: "webhook-1",
    )
    updates: list[object] = []
    publications: list[dict[str, object]] = []
    service = SimpleNamespace(repo=SimpleNamespace(webhook_setting=SimpleNamespace(update=updates.append)))
    monkeypatch.setattr(app_setting_module.InfraHelper, "get_by_id_like", lambda *args: setting)
    monkeypatch.setattr(
        app_setting_module.AppSettingPublisher,
        "webhook_setting_updated",
        lambda uid, model: publications.append(model),
    )

    app_setting_module.AppSettingService.update_webhook_setting(service, "webhook-1", name="Renamed")
    assert setting.events == ["card_created"]

    app_setting_module.AppSettingService.update_webhook_setting(
        service,
        "webhook-1",
        events=None,
        replace_events=True,
    )
    assert setting.events is None
    assert publications[-1] == {"events": None}
    assert updates == [setting, setting]


@pytest.mark.asyncio
async def test_fanout_filters_then_schedules_independent_endpoint_deliveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy and matching endpoints get child tasks; excluded endpoints get none."""

    def setting(uid: str, events: list[str] | None) -> SimpleNamespace:
        return SimpleNamespace(events=events, get_uid=lambda: uid)

    scheduled: list[tuple[WebhookModel, str]] = []

    def schedule(model: WebhookModel, uid: str) -> None:
        scheduled.append((model, uid))

    monkeypatch.setattr(
        WebhookTask,
        "_get_webhook_settings",
        lambda: [
            setting("legacy", None),
            setting("matching", ["card_created"]),
            setting("excluded", ["card_moved"]),
        ],
    )
    monkeypatch.setattr(WebhookTask, "webhook_delivery_task", schedule)
    model = WebhookModel(event="card_created", data={})

    await WebhookTask.run_webhook(model)

    assert scheduled == [(model, "legacy"), (model, "matching")]


@pytest.mark.asyncio
async def test_fanout_retries_only_broker_publish_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial child publish raises the broker error for bounded parent retry."""

    def setting(uid: str) -> SimpleNamespace:
        return SimpleNamespace(events=None, get_uid=lambda: uid)

    attempted: list[str] = []

    def schedule(model: WebhookModel, uid: str) -> None:
        attempted.append(uid)
        if uid == "failed":
            raise WebhookTask.OperationalError("broker unavailable")

    monkeypatch.setattr(
        WebhookTask,
        "_get_webhook_settings",
        lambda: [setting("published"), setting("failed"), setting("not-yet-published")],
    )
    monkeypatch.setattr(WebhookTask, "webhook_delivery_task", schedule)

    with pytest.raises(WebhookTask.OperationalError, match="broker unavailable"):
        await WebhookTask.run_webhook(WebhookModel(event="card_created", data={}))

    assert attempted == ["published", "failed"]
    assert WebhookTask.WEBHOOK_FANOUT_RETRY_OPTIONS == {
        "autoretry_for": (WebhookTask.OperationalError,),
        "retry_backoff": True,
        "retry_backoff_max": 600,
        "retry_jitter": True,
        "retry_kwargs": {"max_retries": 3},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["bot_created", "bot_cron_scheduled"])
async def test_filter_is_rechecked_before_post(monkeypatch: pytest.MonkeyPatch, event: str) -> None:
    """A changed allowlist can cancel a queued event without opening an HTTP client."""

    setting = SimpleNamespace(events=["card_moved"])
    monkeypatch.setattr(WebhookTask, "_get_webhook_setting", lambda uid: setting)

    class UnexpectedClient:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError("filtered delivery opened an HTTP client")

    monkeypatch.setattr(WebhookTask, "AsyncClient", UnexpectedClient)

    await WebhookTask.deliver_webhook(WebhookModel(event=event, data={}), "webhook-1")


@pytest.mark.asyncio
async def test_endpoint_delivery_failure_is_bounded_and_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """One endpoint transport failure surfaces only from its child task."""

    setting = SimpleNamespace(
        secret_id="secret-id",
        url="https://example.invalid/hook",
        events=None,
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

    monkeypatch.setattr(WebhookTask, "_get_webhook_setting", lambda uid: setting)
    monkeypatch.setattr(WebhookTask, "AsyncClient", FakeClient)
    monkeypatch.setattr(WebhookTask.KeyVault, "get_key", lambda key: "secret")

    with pytest.raises(WebhookTask.WebhookDeliveryError, match="endpoint=webhook-1"):
        await WebhookTask.deliver_webhook(WebhookModel(event="card_created", data={}), "webhook-1")

    assert observed_timeout == [WebhookTask.WEBHOOK_TIMEOUT]
    assert WebhookTask.WEBHOOK_DELIVERY_RETRY_OPTIONS == {
        "autoretry_for": (WebhookTask.WebhookDeliveryError,),
        "retry_backoff": True,
        "retry_backoff_max": 600,
        "retry_jitter": True,
        "retry_kwargs": {"max_retries": 3},
    }
    assert WebhookTask.WebhookDeliveryError not in WebhookTask.WEBHOOK_FANOUT_RETRY_OPTIONS["autoretry_for"]
