import asyncio
from typing import Any
from celery import Task
from kombu.exceptions import OperationalError
from ...core.broker import Broker
from ...core.logger import Logger
from ...core.types import SnowflakeID
from ...domain.models import ProjectActivity, ProjectWikiActivity
from ...domain.services import DomainService
from ...helpers import InfraHelper


logger = Logger.use("project-email-notification")


class ProjectEmailDeliveryError(RuntimeError):
    """The configured SMTP transport did not accept an activity email."""


class ProjectEmailDeliveryTask(Task):
    """Persist only a terminal delivery failure after Celery exhausts retries."""

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        if len(args) >= 3:
            activity = _get_activity(str(args[0]), SnowflakeID(args[1]))
            if activity:
                DomainService().project_email_notification.record_delivery(
                    activity,
                    str(args[2]),
                    succeeded=False,
                    error=str(exc),
                )
        super().on_failure(exc, task_id, args, kwargs, einfo)


_FANOUT_RETRY = {
    "autoretry_for": (OperationalError,),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}
_DELIVERY_RETRY = {
    "base": ProjectEmailDeliveryTask,
    "autoretry_for": (ProjectEmailDeliveryError,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}


@Broker.wrap_async_task_decorator(_FANOUT_RETRY)
async def fanout_project_activity_email(activity_table: str, activity_id: SnowflakeID) -> None:
    """Queue one isolated SMTP delivery for each current policy recipient."""

    activity = _get_activity(activity_table, activity_id)
    if not activity:
        return
    service = DomainService().project_email_notification
    recipients = service.get_delivery_recipients(activity)
    logger.info("Scheduling board activity email: activity=%s/%s recipients=%d", activity_table, activity_id, len(recipients))
    for recipient in recipients:
        deliver_project_activity_email(activity_table, activity_id, recipient.email)


@Broker.wrap_async_task_decorator(_DELIVERY_RETRY)
async def deliver_project_activity_email(
    activity_table: str,
    activity_id: SnowflakeID,
    recipient_email: str,
) -> None:
    """Deliver one activity email and fail visibly for bounded retry."""

    activity = _get_activity(activity_table, activity_id)
    if not activity:
        return
    accepted = await asyncio.to_thread(
        DomainService().project_email_notification.send_activity_email,
        activity,
        recipient_email,
    )
    if not accepted:
        raise ProjectEmailDeliveryError(
            f"SMTP delivery failed: activity={activity_table}/{activity_id} recipient={recipient_email}"
        )
    DomainService().project_email_notification.record_delivery(activity, recipient_email, succeeded=True)
    logger.info("Board activity email accepted: activity=%s/%s recipient=%s", activity_table, activity_id, recipient_email)


def _get_activity(
    activity_table: str,
    activity_id: SnowflakeID,
) -> ProjectActivity | ProjectWikiActivity | None:
    model = {
        ProjectActivity.__tablename__: ProjectActivity,
        ProjectWikiActivity.__tablename__: ProjectWikiActivity,
    }.get(activity_table)
    if not model:
        return None
    return InfraHelper.get_by_id_like(model, activity_id)
