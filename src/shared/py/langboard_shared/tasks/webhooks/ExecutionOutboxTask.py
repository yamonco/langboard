"""Single-task execution delivery: claim, fence, signed HTTP, terminal mark."""

from uuid import UUID
from ...core.broker import Broker
from .ExecutionOutboxWorker import ExecutionDeliveryFailed, drain_one


EXECUTION_OUTBOX_RETRY_OPTIONS = {
    "autoretry_for": (ExecutionDeliveryFailed,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}


@Broker.wrap_async_task_decorator(EXECUTION_OUTBOX_RETRY_OPTIONS)
async def execution_outbox_task(event_id: str) -> None:
    """Deliver one committed execution event; the cron recovers lost enqueues."""
    await drain_one(UUID(event_id))
