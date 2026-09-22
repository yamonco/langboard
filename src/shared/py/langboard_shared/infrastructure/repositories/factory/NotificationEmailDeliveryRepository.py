from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....domain.models import NotificationEmailDelivery, UserNotification
from ....domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus


class NotificationEmailDeliveryRepository(BaseRepository[NotificationEmailDelivery]):
    @staticmethod
    def model_cls() -> type[NotificationEmailDelivery]:
        return NotificationEmailDelivery

    @staticmethod
    def name() -> str:
        return "notification_email_delivery"

    def get_review_items(self, limit: int) -> list[NotificationEmailDelivery]:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery)
                .where(
                    NotificationEmailDelivery.column("status").in_(
                        [NotificationEmailDeliveryStatus.Failed, NotificationEmailDeliveryStatus.Uncertain]
                    )
                )
                .order_by(NotificationEmailDelivery.column("created_at"), NotificationEmailDelivery.column("id"))
                .limit(limit)
            ).all()

    def purge_terminal_before(self, older_than: SafeDateTime, limit: int) -> int:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery)
                .where(
                    NotificationEmailDelivery.column("status").in_(
                        [
                            NotificationEmailDeliveryStatus.Sent,
                            NotificationEmailDeliveryStatus.Suppressed,
                            NotificationEmailDeliveryStatus.ConfirmedSent,
                            NotificationEmailDeliveryStatus.Closed,
                        ]
                    )
                    & (NotificationEmailDelivery.column("updated_at") < older_than)
                )
                .order_by(NotificationEmailDelivery.column("updated_at"), NotificationEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            if not deliveries:
                return 0
            return db.exec(
                SqlBuilder.delete.table(NotificationEmailDelivery).where(
                    NotificationEmailDelivery.column("id").in_([delivery.id for delivery in deliveries])
                ),
                purge=True,
            )

    def get_review_item(self, delivery_id: SnowflakeID) -> NotificationEmailDelivery | None:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery).where(
                    NotificationEmailDelivery.column("id") == delivery_id
                )
            ).first()

    def resolve_review_item(
        self,
        delivery_id: SnowflakeID,
        expected_status: NotificationEmailDeliveryStatus,
        target_status: NotificationEmailDeliveryStatus,
        note: str,
    ) -> bool:
        with DbSession.use(readonly=False) as db:
            updated = db.exec(
                SqlBuilder.update.table(NotificationEmailDelivery)
                .values(
                    {
                        NotificationEmailDelivery.column("status"): target_status,
                        NotificationEmailDelivery.column("claimed_at"): None,
                        NotificationEmailDelivery.column("review_note"): note,
                        NotificationEmailDelivery.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (NotificationEmailDelivery.column("id") == delivery_id)
                    & (NotificationEmailDelivery.column("status") == expected_status)
                )
            )
            return updated == 1

    def accept(self, delivery: NotificationEmailDelivery, web_notification: UserNotification | None) -> None:
        with DbSession.use(readonly=False) as db:
            if web_notification is not None:
                db.insert(web_notification)
                delivery.notification_id = web_notification.id
            db.insert(delivery)

    def claim_pending(self, limit: int) -> list[NotificationEmailDelivery]:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery)
                .where(NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Pending)
                .order_by(NotificationEmailDelivery.column("created_at"), NotificationEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            claimed_at = SafeDateTime.now()
            for delivery in deliveries:
                delivery.status = NotificationEmailDeliveryStatus.Preparing
                delivery.claimed_at = claimed_at
                db.update(delivery)
            return deliveries

    def mark_stale_preparing_pending(self, older_than: SafeDateTime, limit: int) -> int:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery)
                .where(
                    (NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Preparing)
                    & (NotificationEmailDelivery.column("claimed_at") <= older_than)
                )
                .order_by(NotificationEmailDelivery.column("claimed_at"), NotificationEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for delivery in deliveries:
                delivery.status = NotificationEmailDeliveryStatus.Pending
                delivery.claimed_at = None
                db.update(delivery)
            return len(deliveries)

    def begin_sending(self, delivery: NotificationEmailDelivery) -> bool:
        claimed_at = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            updated = db.exec(
                SqlBuilder.update.table(NotificationEmailDelivery)
                .values(
                    {
                        NotificationEmailDelivery.column("status"): NotificationEmailDeliveryStatus.Sending,
                        NotificationEmailDelivery.column("claimed_at"): claimed_at,
                        NotificationEmailDelivery.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (NotificationEmailDelivery.column("id") == delivery.id)
                    & (NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Preparing)
                    & (NotificationEmailDelivery.column("claimed_at") == delivery.claimed_at)
                )
            )
            if updated != 1:
                return False
            delivery.status = NotificationEmailDeliveryStatus.Sending
            delivery.claimed_at = claimed_at
            return True

    def mark_stale_uncertain(self, older_than: SafeDateTime, limit: int) -> int:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(NotificationEmailDelivery)
                .where(
                    (NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Sending)
                    & (NotificationEmailDelivery.column("claimed_at") <= older_than)
                )
                .order_by(NotificationEmailDelivery.column("claimed_at"), NotificationEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for delivery in deliveries:
                delivery.status = NotificationEmailDeliveryStatus.Uncertain
                delivery.failure_reason = "Delivery worker exited before recording an SMTP outcome"
                db.update(delivery)
            return len(deliveries)

    def complete_sending(
        self,
        delivery: NotificationEmailDelivery,
        status: NotificationEmailDeliveryStatus,
        failure_reason: str | None = None,
    ) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(NotificationEmailDelivery)
                .values(
                    {
                        NotificationEmailDelivery.column("status"): status,
                        NotificationEmailDelivery.column("sent_at"): (
                            SafeDateTime.now() if status == NotificationEmailDeliveryStatus.Sent else None
                        ),
                        NotificationEmailDelivery.column("failure_reason"): (
                            failure_reason[:1000] if failure_reason else None
                        ),
                        NotificationEmailDelivery.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (NotificationEmailDelivery.column("id") == delivery.id)
                    & (NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Sending)
                    & (NotificationEmailDelivery.column("claimed_at") == delivery.claimed_at)
                )
            )

    def complete_preparing(
        self,
        delivery: NotificationEmailDelivery,
        status: NotificationEmailDeliveryStatus,
        failure_reason: str | None = None,
    ) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(NotificationEmailDelivery)
                .values(
                    {
                        NotificationEmailDelivery.column("status"): status,
                        NotificationEmailDelivery.column("claimed_at"): None,
                        NotificationEmailDelivery.column("failure_reason"): (
                            failure_reason[:1000] if failure_reason else None
                        ),
                        NotificationEmailDelivery.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (NotificationEmailDelivery.column("id") == delivery.id)
                    & (NotificationEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Preparing)
                    & (NotificationEmailDelivery.column("claimed_at") == delivery.claimed_at)
                )
            )
