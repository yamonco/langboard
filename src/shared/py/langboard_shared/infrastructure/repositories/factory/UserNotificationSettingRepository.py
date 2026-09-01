from typing import Literal, Self, overload
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.db.queries.Select import SelectOfScalar
from ....core.domain import BaseRepository
from ....domain.models import User, UserNotificationUnsubscription
from ....domain.models.UserNotification import NotificationType
from ....domain.models.UserNotificationUnsubscription import NotificationChannel, NotificationScope


class UserNotificationSettingRepository(BaseRepository[UserNotificationUnsubscription]):
    @staticmethod
    def model_cls():
        return UserNotificationUnsubscription

    @staticmethod
    def name() -> str:
        return "user_notification_setting"

    def get_unsubscriptions_query_builder(self, user: User):
        class _QueryBuilder:
            def __init__(self, query: SelectOfScalar[UserNotificationUnsubscription]):
                self.__query = query

            def where_channel(self, channel: NotificationChannel):
                return _QueryBuilder(self.__query.where(UserNotificationUnsubscription.column("channel") == channel))

            def where_notification_type(self, notification_type: NotificationType | list[NotificationType]):
                if isinstance(notification_type, list):
                    return _QueryBuilder(
                        self.__query.where(
                            UserNotificationUnsubscription.column("notification_type").in_(notification_type)
                        )
                    )
                return _QueryBuilder(
                    self.__query.where(UserNotificationUnsubscription.column("notification_type") == notification_type)
                )

            @overload
            def where_scope(self, scope: Literal[NotificationScope.All]) -> Self: ...
            @overload
            def where_scope(self, scope: Literal[NotificationScope.Specific], model: BaseDbModel) -> Self: ...
            @overload
            def where_scope(self, scope: Literal[NotificationScope.Specific], model: tuple[str, int]) -> Self: ...
            def where_scope(
                self,
                scope: NotificationScope,
                model: BaseDbModel | tuple[str, int] | None = None,
            ):
                query = self.__query.where(UserNotificationUnsubscription.column("scope_type") == scope)

                if scope == NotificationScope.Specific and model:
                    if isinstance(model, tuple):
                        tablename, record_id = model
                    else:
                        tablename = model.__tablename__
                        record_id = model.id

                    query = self.__query.where(
                        (UserNotificationUnsubscription.column("specific_table") == tablename)
                        & (UserNotificationUnsubscription.column("specific_id") == record_id)
                    )
                return _QueryBuilder(query)

            def all(self):
                records = []
                with DbSession.use(readonly=True) as db:
                    result = db.exec(self.__query)
                    records = result.all()
                return records

            def first(self):
                record = None
                with DbSession.use(readonly=True) as db:
                    result = db.exec(self.__query.limit(1))
                    record = result.first()
                return record

        query = SqlBuilder.select.table(UserNotificationUnsubscription).where(
            UserNotificationUnsubscription.column("user_id") == user.id
        )
        return _QueryBuilder(query)
