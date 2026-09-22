from sqlalchemy import func
from ...core.db import DbSession, SqlBuilder
from ...domain.services import DomainService


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
    with DomainService.use() as service:
        return service.notification.recover_pending_email_delivery()


def purge_terminal_email_deliveries() -> int:
    with DomainService.use() as service:
        return service.notification.purge_terminal_email_deliveries()
