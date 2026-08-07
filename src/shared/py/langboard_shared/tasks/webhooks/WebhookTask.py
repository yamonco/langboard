from hashlib import sha256
from hmac import new as hmac_new
from json import dumps as json_dumps
from time import time
from typing import Any
from httpx import AsyncClient, Timeout
from kombu.exceptions import OperationalError
from ...core.broker import Broker
from ...core.db import DbSession, SqlBuilder
from ...core.security import KeyVault
from ...core.types import SafeDateTime
from ...core.utils.Converter import convert_python_data
from ...domain.models import WebhookSetting
from ...helpers import InfraHelper
from ...publishers import AppSettingPublisher
from .utils import WebhookModel


WEBHOOK_TIMEOUT = Timeout(5.0, connect=2.0)
_SAFE_EVENT_FIELDS = frozenset(
    {
        "card_title",
        "old_project_column_is_archive",
        "old_project_column_name",
        "project_column_is_archive",
        "project_column_name",
        "project_title",
        "reaction_type",
    }
)
_SAFE_EVENT_IDENTIFIERS = frozenset(
    {
        "attachment_uid",
        "card_uid",
        "cardified_card_uid",
        "checkitem_uid",
        "checklist_uid",
        "comment_uid",
        "old_project_column_uid",
        "project_column_uid",
        "project_label_uid",
        "project_uid",
        "project_wiki_uid",
    }
)


class WebhookDeliveryError(RuntimeError):
    """A webhook endpoint rejected an event delivery."""


WEBHOOK_FANOUT_RETRY_OPTIONS = {
    "autoretry_for": (OperationalError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}
WEBHOOK_DELIVERY_RETRY_OPTIONS = {
    "autoretry_for": (WebhookDeliveryError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}


@Broker.wrap_async_task_decorator(WEBHOOK_FANOUT_RETRY_OPTIONS)
async def webhook_task(model: WebhookModel) -> None:
    """Fan out one stable event and retry only child publish failures."""

    await run_webhook(model)


@Broker.wrap_async_task_decorator(WEBHOOK_DELIVERY_RETRY_OPTIONS)
async def webhook_delivery_task(model: WebhookModel, webhook_uid: str) -> None:
    """Deliver one event to one endpoint with an independent retry budget."""

    await deliver_webhook(model, webhook_uid)


async def run_webhook(model: WebhookModel) -> None:
    """Schedule one delivery task for each endpoint that accepts the event."""

    settings = _get_webhook_settings()
    for setting in settings:
        if not _accepts_event(setting, model.event):
            continue
        try:
            webhook_delivery_task(model, setting.get_uid())
        except OperationalError as error:
            Broker.logger.error(
                "Webhook delivery scheduling failed: endpoint=%s error=%s",
                setting.get_uid(),
                type(error).__name__,
            )
            raise


async def deliver_webhook(model: WebhookModel, webhook_uid: str) -> None:
    """POST one event to one current endpoint with bounded I/O."""

    setting = _get_webhook_setting(webhook_uid)
    if not setting or not _accepts_event(setting, model.event):
        return

    try:
        secret = KeyVault.get_key(setting.secret_id) if setting.secret_id else None
        body, headers = signed_request(model, secret)
        async with AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            response = await client.post(setting.url, content=body, headers=headers)
            response.raise_for_status()
    except Exception as error:
        Broker.logger.error(
            "Webhook delivery failed: endpoint=%s error=%s",
            webhook_uid,
            type(error).__name__,
        )
        raise WebhookDeliveryError(f"Webhook delivery failed: endpoint={webhook_uid}") from error

    setting.last_used_at = SafeDateTime.now()
    setting.total_used_count += 1
    with DbSession.use(readonly=False) as db:
        db.update(setting)
    AppSettingPublisher.webhook_setting_updated(
        webhook_uid,
        {
            "last_used_at": setting.last_used_at,
            "total_used_count": setting.total_used_count,
        },
    )


def signed_request(
    model: WebhookModel,
    secret: str | None,
    *,
    timestamp: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Serialize one canonical payload and add optional HMAC headers."""

    payload = {
        "schema_version": model.schema_version,
        "event_id": model.event_id,
        "occurred_at": model.occurred_at,
        "event": model.event,
        "data": minimal_event_data(model.data),
    }
    body = json_dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    delivered_at = str(timestamp if timestamp is not None else int(time()))
    headers = {
        "Content-Type": "application/json",
        "X-Langboard-Webhook-Id": model.event_id,
        "X-Langboard-Webhook-Timestamp": delivered_at,
        "X-Langboard-Webhook-Version": model.schema_version,
    }
    if secret:
        signature = hmac_new(
            secret.encode("utf-8"),
            delivered_at.encode("ascii") + b"." + body,
            sha256,
        ).hexdigest()
        headers["X-Langboard-Webhook-Signature"] = f"v1={signature}"
    return body, headers


def minimal_event_data(data: dict[str, Any]) -> dict[str, Any]:
    """Project bot-trigger data to non-PII webhook routing metadata."""

    result = {
        key: convert_python_data(value, recursive=True)
        for key, value in data.items()
        if key in _SAFE_EVENT_IDENTIFIERS or key in _SAFE_EVENT_FIELDS
    }
    executor = data.get("executor")
    if isinstance(executor, dict) and isinstance(executor.get("uid"), str):
        executor_type = executor.get("type")
        if not isinstance(executor_type, str):
            executor_type = "bot" if "bot_uname" in executor else "unknown"
        result["executor"] = {
            "uid": executor["uid"],
            "type": executor_type,
            "display_name": _executor_display_name(executor, executor_type),
        }
    return result


def _executor_display_name(executor: dict[str, Any], executor_type: str) -> str:
    """Freeze the safe actor label used by downstream notifications."""

    if executor_type == "user":
        full_name = " ".join(
            part.strip()
            for part in (executor.get("firstname"), executor.get("lastname"))
            if isinstance(part, str) and part.strip()
        )
        if full_name:
            return full_name
        username = executor.get("username")
        return username.strip() if isinstance(username, str) and username.strip() else "알 수 없음"
    if executor_type == "bot":
        name = executor.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else "Langboard"
    return "알 수 없음"


def _get_webhook_settings() -> list[WebhookSetting]:
    urls = None
    with DbSession.use(readonly=True) as db:
        result = db.exec(SqlBuilder.select.table(WebhookSetting))
        urls = result.all()
    if not urls:
        return []
    if not isinstance(urls, list):
        return []

    return urls


def _get_webhook_setting(webhook_uid: str) -> WebhookSetting | None:
    return InfraHelper.get_by_id_like(WebhookSetting, webhook_uid)


def _accepts_event(setting: WebhookSetting, event: str) -> bool:
    events = setting.events
    return events is None or event in events
