import asyncio
from kombu.exceptions import OperationalError
from ...core.broker import Broker
from ...core.logger import Logger
from ...core.types import SnowflakeID
from ...domain.models import ProjectActivity, ProjectActivityEmailDelivery, ProjectWikiActivity
from ...domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus
from ...domain.services import DomainService
from ...Env import Env
from ...helpers import InfraHelper
from .ProjectEmailNotificationQueue import register_project_activity_email_task


logger = Logger.use("project-email-notification")


_FANOUT_RETRY = {
    "autoretry_for": (OperationalError,),
    "retry_backoff": True,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 3},
    "acks_late": True,
    "reject_on_worker_lost": True,
}


@Broker.wrap_async_task_decorator(_FANOUT_RETRY)
async def fanout_project_activity_email(activity_table: str, activity_id: SnowflakeID) -> None:
    activity = _get_activity(activity_table, activity_id)
    if activity is None:
        return
    with DomainService.use() as service:
        deliveries = _accept_fanout(service, activity)
    logger.info(
        "Queued board activity email: activity=%s/%s recipients=%d", activity_table, activity_id, len(deliveries)
    )
    if Env.MAIL_SERVER and Env.MAIL_FROM:
        for delivery in deliveries:
            if delivery.status == NotificationEmailDeliveryStatus.Pending:
                deliver_project_activity_email(activity_table, activity_id, delivery.recipient_email)


def register() -> None:
    register_project_activity_email_task(fanout_project_activity_email)


@Broker.wrap_async_task_decorator
async def deliver_project_activity_email(activity_table: str, activity_id: SnowflakeID, recipient_email: str) -> None:
    await asyncio.to_thread(_deliver_project_activity_email, activity_table, activity_id, recipient_email)


def _deliver_project_activity_email(activity_table: str, activity_id: SnowflakeID, recipient_email: str) -> bool:
    activity = _get_activity(activity_table, activity_id)
    if activity is None:
        return False
    with DomainService.use() as service:
        repository = service.project_email_notification.repo.project_activity_email_delivery
        delivery = repository.accept_one(activity, recipient_email)
        if delivery is None:
            return False
        delivery = repository.claim_one(delivery.id)
        if delivery is None:
            return False
        return _deliver_claimed(service, delivery)


def recover_pending_project_activity_email(limit: int = 8) -> int:
    with DomainService.use() as service:
        repository = service.project_email_notification.repo.project_activity_email_delivery
        for activity in repository.get_pending_fanout(limit):
            try:
                _accept_fanout(service, activity)
            except Exception:
                logger.exception(
                    "Cannot recover project activity email fanout %s/%s", activity.__tablename__, activity.id
                )
                repository.defer_pending_fanout(activity)
        repository.recover_stale(limit)
        if not Env.MAIL_SERVER or not Env.MAIL_FROM:
            return 0
        deliveries = repository.claim_pending(limit)
        return sum(_deliver_claimed(service, delivery) for delivery in deliveries)


def _accept_fanout(
    service: DomainService, activity: ProjectActivity | ProjectWikiActivity
) -> list[ProjectActivityEmailDelivery]:
    recipients = service.project_email_notification.get_delivery_recipients(activity)
    return service.project_email_notification.repo.project_activity_email_delivery.accept_recipients(
        activity, [recipient.email for recipient in recipients]
    )


def _deliver_claimed(service: DomainService, delivery: ProjectActivityEmailDelivery) -> bool:
    repository = service.project_email_notification.repo.project_activity_email_delivery
    activity = _get_activity(delivery.activity_table, delivery.activity_id)
    if activity is None:
        repository.complete(delivery, NotificationEmailDeliveryStatus.Suppressed, "Activity is no longer available")
        return False

    try:
        message = service.project_email_notification.prepare_activity_email(activity, delivery.recipient_email)
    except Exception:
        logger.exception("Cannot prepare board activity email %s", delivery.id)
        repository.complete(delivery, NotificationEmailDeliveryStatus.Failed, "Email preparation failed")
        return False
    if message is None:
        repository.complete(delivery, NotificationEmailDeliveryStatus.Suppressed, "Recipient is no longer eligible")
        return False
    if not repository.begin_sending(delivery):
        return False

    try:
        accepted = service.email.send_message(message, strict=True)
    except Exception:
        logger.exception("Cannot confirm board activity SMTP outcome %s", delivery.id)
        accepted = False

    completed = repository.complete(
        delivery,
        NotificationEmailDeliveryStatus.Sent if accepted else NotificationEmailDeliveryStatus.Uncertain,
        None if accepted else "SMTP acceptance could not be confirmed",
    )
    if accepted and completed:
        service.project_email_notification.record_delivery(activity, delivery.recipient_email, succeeded=True)
        return True
    return False


def _get_activity(activity_table: str, activity_id: SnowflakeID) -> ProjectActivity | ProjectWikiActivity | None:
    model = {
        ProjectActivity.__tablename__: ProjectActivity,
        ProjectWikiActivity.__tablename__: ProjectWikiActivity,
    }.get(activity_table)
    if model is None:
        return None
    return InfraHelper.get_by_id_like(model, activity_id)


register()
