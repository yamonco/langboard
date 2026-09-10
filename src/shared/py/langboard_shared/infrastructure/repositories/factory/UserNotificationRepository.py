from datetime import timedelta
from typing import Literal
from dateutil.relativedelta import relativedelta
from sqlalchemy import String
from sqlalchemy import cast as sql_cast
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TUserParam
from ....domain.models import UserNotification
from ....domain.models.UserNotification import NotificationType
from ....helpers import InfraHelper


class UserNotificationRepository(BaseRepository[UserNotification]):
    @staticmethod
    def model_cls():
        return UserNotification

    @staticmethod
    def name() -> str:
        return "user_notification"

    def get_list(
        self,
        user: TUserParam,
        time_range: Literal["3d", "7d", "1m", "all"] = "3d",
        page: int = 1,
        limit: int = 20,
    ):
        user_id = InfraHelper.convert_id(user)
        query = (
            SqlBuilder.select.table(UserNotification)
            .where(UserNotification.column("receiver_id") == user_id)
            .where(UserNotification.column("web_visible") == True)  # noqa: E712
        )

        if time_range.endswith("d"):
            days = int(time_range[:-1])
            query = query.where(UserNotification.column("created_at") >= SafeDateTime.now() - timedelta(days=days))
        elif time_range.endswith("m"):
            month = int(time_range[:-1])
            query = query.where(
                UserNotification.column("created_at") >= SafeDateTime.now() - relativedelta(months=month)
            )

        query = query.order_by(
            UserNotification.column("created_at").desc(),
            UserNotification.column("id").desc(),
        )
        query = query.limit(limit + 1).offset((page - 1) * limit)

        notifications = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            notifications = result.all()

        return notifications

    def get_project_invitation_notification(self, user: TUserParam, record_list: str) -> UserNotification | None:
        user_id = InfraHelper.convert_id(user)
        notification = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(UserNotification)
                .where(
                    (UserNotification.column("receiver_id") == user_id)
                    & (UserNotification.column("notification_type") == NotificationType.ProjectInvited)
                    & (sql_cast(UserNotification.column("record_list"), String) == record_list)
                )
                .limit(1)
            )
            notification = result.first()
        return notification

    def get_pending_work_events(self, limit: int = 100) -> list[UserNotification]:
        """Read a bounded durable work-event backlog from the primary database."""

        eligible_types = [
            NotificationType.AssignedToCard,
            NotificationType.MentionedInCard,
            NotificationType.MentionedInComment,
            NotificationType.MentionedInWiki,
            NotificationType.NotifiedFromChecklist,
            NotificationType.ProjectInvited,
            NotificationType.ScheduledRule,
        ]
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(UserNotification)
                .where(UserNotification.column("notification_type").in_(eligible_types))
                .where(UserNotification.column("work_event_dispatched_at") == None)  # noqa: E711
                .order_by(UserNotification.column("created_at").asc(), UserNotification.column("id").asc())
                .limit(max(1, min(limit, 100)))
            ).all()

    def mark_work_event_dispatched(self, notification: UserNotification) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(UserNotification)
                .values(work_event_dispatched_at=SafeDateTime.now())
                .where(UserNotification.column("id") == notification.id)
                .where(UserNotification.column("work_event_dispatched_at") == None)  # noqa: E711
            )

    def count_unread(self, user: TUserParam) -> int:
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.count(UserNotification, UserNotification.column("id")).where(
                    (UserNotification.column("receiver_id") == user_id)
                    & (UserNotification.column("web_visible") == True)  # noqa: E712
                    & (UserNotification.column("read_at") == None)  # noqa: E711
                )
            )
            return result.first() or 0

    def read_all_by_user(self, user: TUserParam):
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(UserNotification)
                .values({UserNotification.column("read_at"): SafeDateTime.now()})
                .where(
                    (UserNotification.column("receiver_id") == user_id)
                    & (UserNotification.column("web_visible") == True)  # noqa: E712
                    & (UserNotification.column("read_at") == None)  # noqa: E711
                )
            )

    def delete_all(self, user: TUserParam):
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=False) as db:
            db.exec(SqlBuilder.delete.table(UserNotification).where(UserNotification.column("receiver_id") == user_id))

    def delete_all_by_ids(self, notification_ids: list[int]):
        if not notification_ids:
            return
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(UserNotification).where(UserNotification.column("id").in_(notification_ids))
            )
