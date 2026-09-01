from typing import Any
from httpx import stream
from ...core.broker import Broker
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ...core.utils.Converter import convert_python_data
from ...domain.models import WebhookSetting
from ...Env import Env
from ...publishers import AppSettingPublisher
from .utils import WebhookModel


@Broker.wrap_async_task_decorator
async def webhook_task(model: WebhookModel):
    await run_webhook(model.event, model.data)


async def run_webhook(event: str, data: dict[str, Any]):
    settings = _get_webhook_settings()
    if not settings:
        return

    payload = {"event": event, "data": convert_python_data(data, recursive=True)}
    for setting in settings:
        succeeded = False
        try:
            with stream(
                "POST",
                setting.url,
                json=payload,
                timeout=Env.AI_REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
            succeeded = True
        except Exception as error:
            Broker.logger.error(
                "Failed to request webhook: \nURL: %s\nError: %s: %s",
                setting.url,
                type(error).__name__,
                error,
            )

        if succeeded:
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
