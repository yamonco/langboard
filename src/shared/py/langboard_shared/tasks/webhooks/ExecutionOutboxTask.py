"""Fast path for one committed execution event; cron recovers lost enqueues."""

from uuid import UUID
from ...core.broker import Broker
from .ExecutionOutboxWorker import drain_one


@Broker.wrap_async_task_decorator
async def execution_outbox_task(event_id: str) -> None:
    drain_one(UUID(event_id))
