from datetime import timedelta
from sqlalchemy import func
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....domain.models import ProjectActivity, ProjectActivityEmailDelivery, ProjectWikiActivity
from ....domain.models.NotificationEmailDelivery import NotificationEmailDeliveryStatus


FANOUT_MARKER_EMAIL = ""


class ProjectActivityEmailDeliveryRepository(BaseRepository[ProjectActivityEmailDelivery]):
    @staticmethod
    def model_cls() -> type[ProjectActivityEmailDelivery]:
        return ProjectActivityEmailDelivery

    @staticmethod
    def name() -> str:
        return "project_activity_email_delivery"

    def get_pending_fanout(self, limit: int) -> list[ProjectActivity | ProjectWikiActivity]:
        with DbSession.use(readonly=False) as db:
            pending: list[ProjectActivity | ProjectWikiActivity] = []
            for model in (ProjectActivity, ProjectWikiActivity):
                pending.extend(
                    db.exec(
                        SqlBuilder.select.table(model)
                        .where(
                            (model.column("email_fanout_pending") == True)  # noqa: E712
                            & (
                                model.column("email_fanout_retry_at").is_(None)
                                | (model.column("email_fanout_retry_at") <= SafeDateTime.now())
                            )
                        )
                        .order_by(
                            func.coalesce(model.column("email_fanout_retry_at"), model.column("created_at")),
                            model.column("id"),
                        )
                        .limit(limit)
                    ).all()
                )
            return pending

    def defer_pending_fanout(self, activity: ProjectActivity | ProjectWikiActivity) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(type(activity))
                .values(email_fanout_retry_at=SafeDateTime.now() + timedelta(minutes=5))
                .where(
                    (type(activity).column("id") == activity.id)
                    & (type(activity).column("email_fanout_pending") == True)  # noqa: E712
                )
            )

    def accept_recipients(
        self, activity: ProjectActivity | ProjectWikiActivity, emails: list[str]
    ) -> list[ProjectActivityEmailDelivery]:
        with DbSession.use(readonly=False) as db:
            locked = db.exec(
                SqlBuilder.select.table(type(activity))
                .where(type(activity).column("id") == activity.id)
                .with_for_update()
            ).first()
            if locked is None:
                return []
            existing = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery).where(
                    (ProjectActivityEmailDelivery.column("activity_table") == activity.__tablename__)
                    & (ProjectActivityEmailDelivery.column("activity_id") == activity.id)
                )
            ).all()
            existing_by_email = {delivery.recipient_email: delivery for delivery in existing}
            if FANOUT_MARKER_EMAIL in existing_by_email:
                locked.email_fanout_pending = False
                db.update(locked)
                return [delivery for delivery in existing if delivery.recipient_email != FANOUT_MARKER_EMAIL]

            recipients = list(dict.fromkeys(email.casefold() for email in emails))
            new_deliveries = [
                ProjectActivityEmailDelivery(
                    project_id=activity.project_id,
                    activity_table=activity.__tablename__,
                    activity_id=activity.id,
                    recipient_email=email.casefold(),
                )
                for email in recipients
                if email not in existing_by_email
            ]
            marker = ProjectActivityEmailDelivery(
                project_id=activity.project_id,
                activity_table=activity.__tablename__,
                activity_id=activity.id,
                recipient_email=FANOUT_MARKER_EMAIL,
                status=NotificationEmailDeliveryStatus.Suppressed,
            )
            db.insert_all([marker, *new_deliveries])
            locked.email_fanout_pending = False
            db.update(locked)
            all_by_email = {**existing_by_email, **{delivery.recipient_email: delivery for delivery in new_deliveries}}
            return [all_by_email[email] for email in recipients]

    def claim_pending(self, limit: int) -> list[ProjectActivityEmailDelivery]:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(ProjectActivityEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Pending)
                .order_by(ProjectActivityEmailDelivery.column("created_at"), ProjectActivityEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            claimed_at = SafeDateTime.now()
            for delivery in deliveries:
                delivery.status = NotificationEmailDeliveryStatus.Preparing
                delivery.claimed_at = claimed_at
                db.update(delivery)
            return deliveries

    def accept_one(
        self, activity: ProjectActivity | ProjectWikiActivity, recipient_email: str
    ) -> ProjectActivityEmailDelivery | None:
        email = recipient_email.casefold()
        if not email:
            return None
        with DbSession.use(readonly=False) as db:
            locked = db.exec(
                SqlBuilder.select.table(type(activity))
                .where(type(activity).column("id") == activity.id)
                .with_for_update()
            ).first()
            if locked is None:
                return None
            delivery = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery).where(
                    (ProjectActivityEmailDelivery.column("activity_table") == activity.__tablename__)
                    & (ProjectActivityEmailDelivery.column("activity_id") == activity.id)
                    & (ProjectActivityEmailDelivery.column("recipient_email") == email)
                )
            ).first()
            if delivery is not None:
                return delivery
            marker = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery).where(
                    (ProjectActivityEmailDelivery.column("activity_table") == activity.__tablename__)
                    & (ProjectActivityEmailDelivery.column("activity_id") == activity.id)
                    & (ProjectActivityEmailDelivery.column("recipient_email") == FANOUT_MARKER_EMAIL)
                )
            ).first()
            if marker is not None:
                return None
            delivery = ProjectActivityEmailDelivery(
                project_id=activity.project_id,
                activity_table=activity.__tablename__,
                activity_id=activity.id,
                recipient_email=email,
            )
            db.insert(delivery)
            return delivery

    def claim_one(self, delivery_id: SnowflakeID) -> ProjectActivityEmailDelivery | None:
        with DbSession.use(readonly=False) as db:
            delivery = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(
                    (ProjectActivityEmailDelivery.column("id") == delivery_id)
                    & (ProjectActivityEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Pending)
                )
                .with_for_update(skip_locked=True)
            ).first()
            if delivery is None:
                return None
            delivery.status = NotificationEmailDeliveryStatus.Preparing
            delivery.claimed_at = SafeDateTime.now()
            db.update(delivery)
            return delivery

    def begin_sending(self, delivery: ProjectActivityEmailDelivery) -> bool:
        claimed_at = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            updated = db.exec(
                SqlBuilder.update.table(ProjectActivityEmailDelivery)
                .values(status=NotificationEmailDeliveryStatus.Sending, claimed_at=claimed_at)
                .where(
                    (ProjectActivityEmailDelivery.column("id") == delivery.id)
                    & (ProjectActivityEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Preparing)
                    & (ProjectActivityEmailDelivery.column("claimed_at") == delivery.claimed_at)
                )
            )
        if updated == 1:
            delivery.status = NotificationEmailDeliveryStatus.Sending
            delivery.claimed_at = claimed_at
            return True
        return False

    def complete(
        self,
        delivery: ProjectActivityEmailDelivery,
        status: NotificationEmailDeliveryStatus,
        reason: str | None = None,
    ) -> bool:
        with DbSession.use(readonly=False) as db:
            updated = db.exec(
                SqlBuilder.update.table(ProjectActivityEmailDelivery)
                .values(
                    status=status,
                    claimed_at=None,
                    sent_at=SafeDateTime.now() if status == NotificationEmailDeliveryStatus.Sent else None,
                    failure_reason=reason[:1000] if reason else None,
                    updated_at=SafeDateTime.now(),
                )
                .where(
                    (ProjectActivityEmailDelivery.column("id") == delivery.id)
                    & (ProjectActivityEmailDelivery.column("status") == delivery.status)
                    & (ProjectActivityEmailDelivery.column("claimed_at") == delivery.claimed_at)
                )
            )
            return updated == 1

    def recover_stale(self, limit: int) -> tuple[int, int]:
        cutoff = SafeDateTime.now() - timedelta(minutes=10)
        with DbSession.use(readonly=False) as db:
            preparing = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(
                    (ProjectActivityEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Preparing)
                    & (ProjectActivityEmailDelivery.column("claimed_at") <= cutoff)
                )
                .order_by(ProjectActivityEmailDelivery.column("claimed_at"), ProjectActivityEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for delivery in preparing:
                delivery.status = NotificationEmailDeliveryStatus.Pending
                delivery.claimed_at = None
                db.update(delivery)
            sending = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(
                    (ProjectActivityEmailDelivery.column("status") == NotificationEmailDeliveryStatus.Sending)
                    & (ProjectActivityEmailDelivery.column("claimed_at") <= cutoff)
                )
                .order_by(ProjectActivityEmailDelivery.column("claimed_at"), ProjectActivityEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for delivery in sending:
                delivery.status = NotificationEmailDeliveryStatus.Uncertain
                delivery.failure_reason = "Delivery worker exited before recording an SMTP outcome"
                db.update(delivery)
            return len(preparing), len(sending)

    def count_for_review(self) -> int:
        with DbSession.use(readonly=False) as db:
            count = db.exec(
                SqlBuilder.select.column(func.count(ProjectActivityEmailDelivery.column("id"))).where(
                    ProjectActivityEmailDelivery.column("status").in_(
                        [NotificationEmailDeliveryStatus.Failed, NotificationEmailDeliveryStatus.Uncertain]
                    )
                )
            ).first()
            return int(count or 0)

    def get_review_items(self, limit: int) -> list[ProjectActivityEmailDelivery]:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(
                    ProjectActivityEmailDelivery.column("status").in_(
                        [NotificationEmailDeliveryStatus.Failed, NotificationEmailDeliveryStatus.Uncertain]
                    )
                )
                .order_by(ProjectActivityEmailDelivery.column("created_at"), ProjectActivityEmailDelivery.column("id"))
                .limit(limit)
            ).all()

    def get_review_item(self, delivery_id: SnowflakeID) -> ProjectActivityEmailDelivery | None:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery).where(
                    ProjectActivityEmailDelivery.column("id") == delivery_id
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
                SqlBuilder.update.table(ProjectActivityEmailDelivery)
                .values(
                    status=target_status,
                    claimed_at=None,
                    review_note=note,
                    updated_at=SafeDateTime.now(),
                )
                .where(
                    (ProjectActivityEmailDelivery.column("id") == delivery_id)
                    & (ProjectActivityEmailDelivery.column("status") == expected_status)
                )
            )
            return updated == 1

    def purge_terminal_before(self, older_than: SafeDateTime, limit: int) -> int:
        with DbSession.use(readonly=False) as db:
            deliveries = db.exec(
                SqlBuilder.select.table(ProjectActivityEmailDelivery)
                .where(
                    ProjectActivityEmailDelivery.column("status").in_(
                        [
                            NotificationEmailDeliveryStatus.Sent,
                            NotificationEmailDeliveryStatus.Suppressed,
                            NotificationEmailDeliveryStatus.ConfirmedSent,
                            NotificationEmailDeliveryStatus.Closed,
                        ]
                    )
                    & (ProjectActivityEmailDelivery.column("recipient_email") != FANOUT_MARKER_EMAIL)
                    & (ProjectActivityEmailDelivery.column("updated_at") < older_than)
                )
                .order_by(ProjectActivityEmailDelivery.column("updated_at"), ProjectActivityEmailDelivery.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            if not deliveries:
                return 0
            return db.exec(
                SqlBuilder.delete.table(ProjectActivityEmailDelivery).where(
                    ProjectActivityEmailDelivery.column("id").in_([delivery.id for delivery in deliveries])
                ),
                purge=True,
            )
