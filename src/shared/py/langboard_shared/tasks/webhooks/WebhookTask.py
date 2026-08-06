from hashlib import sha256
from hmac import new as hmac_new
from json import dumps as json_dumps
from time import time
from typing import Any
from httpx import AsyncClient, Timeout
from ...core.broker import Broker
from ...core.db import DbSession, SqlBuilder
from ...core.security import KeyVault
from ...core.types import SafeDateTime
from ...core.utils.Converter import convert_python_data
from ...domain.models import WebhookSetting
from ...publishers import AppSettingPublisher
from .utils import WebhookModel


WEBHOOK_TIMEOUT = Timeout(5.0, connect=2.0)
_SAFE_EVENT_FIELDS = frozenset({"reaction_type"})
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
    """One or more webhook endpoints rejected an event delivery."""


@Broker.wrap_async_task_decorator(
    {
        "autoretry_for": (WebhookDeliveryError,),
        "retry_backoff": True,
        "retry_jitter": True,
        "retry_kwargs": {"max_retries": 3},
    }
)
async def webhook_task(model: WebhookModel):
    """Deliver one stable event through the existing Celery task."""

    await run_webhook(model)


async def run_webhook(model: WebhookModel) -> None:
    """Deliver an event to every configured endpoint with bounded I/O."""

    settings = _get_webhook_settings()
    if not settings:
        return

    failures = 0
    async with AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
        for setting in settings:
            try:
                secret = KeyVault.get_key(setting.secret_id) if setting.secret_id else None
                body, headers = signed_request(model, secret)
                response = await client.post(setting.url, content=body, headers=headers)
                response.raise_for_status()
            except Exception as error:
                failures += 1
                Broker.logger.error(
                    "Webhook delivery failed: endpoint=%s error=%s",
                    setting.get_uid(),
                    type(error).__name__,
                )
                continue

            setting.last_used_at = SafeDateTime.now()
            setting.total_used_count += 1
            with DbSession.use(readonly=False) as db:
                db.update(setting)
            AppSettingPublisher.webhook_setting_updated(
                setting.get_uid(),
                {
                    "last_used_at": setting.last_used_at,
                    "total_used_count": setting.total_used_count,
                },
            )
    if failures:
        raise WebhookDeliveryError(f"{failures} webhook delivery attempt(s) failed")


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
        result["executor"] = {"uid": executor["uid"], "type": executor_type}
    return result


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
