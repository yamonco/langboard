"""API worker registration; shared broker never imports API policy."""

from langboard_shared.core.broker import Broker
from langboard_shared.domain.services import DomainService
from .GitHubHealthWorker import drain_one


@Broker.wrap_async_task_decorator
async def github_health_task(job_uid: str) -> None:
    service = DomainService()
    try:
        drain_one(service, job_uid)
    finally:
        service.close()
