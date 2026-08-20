import asyncio
from kombu.exceptions import OperationalError
from ...core.broker import Broker
from ...core.logger import Logger
from ...core.types import SnowflakeID
from ...domain.models import ProjectActivity, ProjectWikiActivity, User
from ...domain.services import DomainService
from ...helpers import InfraHelper


logger = Logger.use("project-email-notification")


class ProjectEmailDeliveryError(RuntimeError):
    """The configured SMTP transport did not accept an activity email."""


_FANOUT_RETRY = {
    "autoretry_for": (OperationalError,),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
}
_DELIVERY_RETRY = {
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
    recipient_ids = service.get_delivery_recipient_ids(activity)
    logger.info("Scheduling board activity email: activity=%s/%s recipients=%d", activity_table, activity_id, len(recipient_ids))
    for recipient_id in recipient_ids:
        deliver_project_activity_email(activity_table, activity_id, recipient_id)


@Broker.wrap_async_task_decorator(_DELIVERY_RETRY)
async def deliver_project_activity_email(
    activity_table: str,
    activity_id: SnowflakeID,
    recipient_id: SnowflakeID,
) -> None:
    """Deliver one activity email and fail visibly for bounded retry."""

    activity = _get_activity(activity_table, activity_id)
    recipient = InfraHelper.get_by_id_like(User, recipient_id)
    if not activity or not recipient:
        return
    accepted = await asyncio.to_thread(
        DomainService().project_email_notification.send_activity_email,
        activity,
        recipient,
    )
    if not accepted:
        raise ProjectEmailDeliveryError(
            f"SMTP delivery failed: activity={activity_table}/{activity_id} recipient={recipient_id}"
        )
    logger.info("Board activity email accepted: activity=%s/%s recipient=%s", activity_table, activity_id, recipient_id)


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
