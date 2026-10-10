from sqlalchemy import func
from ...core.db import DbSession, SqlBuilder
from ...domain.services import DomainService
from .ProjectEmailNotificationTask import recover_pending_project_activity_email


def recover_pending_web_fanout() -> int:
    with DbSession.use(readonly=False) as db:
        acquired = db.exec(
            SqlBuilder.select.column(
                func.pg_try_advisory_xact_lock(func.hashtextextended("notification:web-fanout", 0))
            )
        ).first()
        if not acquired:
            return 0

        with DomainService.use() as service:
            return service.notification.recover_pending_web_fanout()


def recover_pending_email_delivery() -> int:
    completed = 0
    try:
        with DomainService.use() as service:
            completed = service.notification.recover_pending_email_delivery()
    finally:
        project_completed = recover_pending_project_activity_email()
    return completed + project_completed


def purge_terminal_email_deliveries() -> int:
    with DomainService.use() as service:
        return (
            service.notification.purge_terminal_email_deliveries()
            + service.project_email_notification.purge_terminal_deliveries()
        )
