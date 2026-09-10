from kombu.exceptions import OperationalError
from ...core.broker import Broker
from ...infrastructure.repositories import Repository
from ..webhooks.utils import build_notification_work_event
from ..webhooks.WebhookTask import run_webhook


WORK_EVENT_RETRY_OPTIONS = {
    "autoretry_for": (OperationalError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 5},
}


@Broker.wrap_async_task_decorator(WORK_EVENT_RETRY_OPTIONS)
async def publish_pending_work_events() -> None:
    """Drain a bounded durable notification backlog into stable signed work events."""

    await drain_pending_work_events(Repository())


async def drain_pending_work_events(repository: Repository) -> None:
    """Publish only committed notifications and mark them after fan-out is scheduled."""

    for notification in repository.user_notification.get_pending_work_events(limit=100):
        work_event = build_notification_work_event(notification)
        if work_event is None:
            repository.user_notification.mark_work_event_dispatched(notification)
            continue
        await run_webhook(work_event)
        repository.user_notification.mark_work_event_dispatched(notification)
