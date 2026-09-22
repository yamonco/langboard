from typing import Literal, cast, overload
from ....core.db import BaseDbModel
from ....core.domain import BaseDomainService
from ....core.types.ParamTypes import TCardParam, TColumnParam, TProjectParam, TWikiParam
from ....helpers import InfraHelper
from ...models import Card, Project, ProjectColumn, ProjectWiki, User, UserNotificationUnsubscription
from ...models.UserNotification import NotificationType
from ...models.UserNotificationUnsubscription import NotificationChannel, NotificationScope


class UserNotificationSettingService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "user_notification_setting"

    def get_api_map_by_user(self, user: User):
        notification_unsubs = self.repo.user_notification_setting.get_unsubscriptions_query_builder(user).all()
        unsubs: dict[str, dict[str, dict[str, bool | list[str]]]] = {}
        for unsub in notification_unsubs:
            if unsub.scope_type.value not in unsubs:
                unsubs[unsub.scope_type.value] = {}
            unsubs_scope = unsubs[unsub.scope_type.value]
            if unsub.notification_type.value not in unsubs_scope:
                unsubs_scope[unsub.notification_type.value] = {}
            unsubs_type = unsubs_scope[unsub.notification_type.value]

            if unsub.scope_type == NotificationScope.All:
                unsubs_type[unsub.channel.value] = True
                continue

            if not unsub.specific_id:
                continue

            if unsub.channel.value not in unsubs_type:
                unsubs_type[unsub.channel.value] = []
            cast(list, unsubs_type[unsub.channel.value]).append(unsub.specific_id.to_short_code())
        return unsubs

    @overload
    def subscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: Literal[NotificationScope.All],
    ) -> list[NotificationType]: ...
    @overload
    def subscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: Literal[NotificationScope.Specific],
        model: BaseDbModel,
    ) -> list[NotificationType]: ...
    def subscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: NotificationScope,
        model: BaseDbModel | None = None,
    ):
        if not isinstance(notification_types, list):
            notification_types = [notification_types]

        for notification_type in [*notification_types]:
            if notification_type in UserNotificationUnsubscription.UNAVAILABLE_TYPES:
                notification_types.remove(notification_type)

        query = self.repo.user_notification_setting.get_unsubscriptions_query_builder(user)
        query = query.where_channel(channel).where_notification_type(notification_types)
        if scope == NotificationScope.Specific:
            if not model:
                return False
            query = query.where_scope(scope, model)
        else:
            query = query.where_scope(scope)

        unsubscriptions = query.all()

        for unsubscription in unsubscriptions:
            self.repo.user_notification_setting.delete(unsubscription)

        return notification_types

    @overload
    def unsubscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: Literal[NotificationScope.All],
    ) -> list[NotificationType]: ...
    @overload
    def unsubscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: Literal[NotificationScope.Specific],
        model: BaseDbModel,
    ) -> list[NotificationType]: ...
    def unsubscribe(
        self,
        user: User,
        channel: NotificationChannel,
        notification_types: NotificationType | list[NotificationType],
        scope: NotificationScope,
        model: BaseDbModel | None = None,
    ):
        if not isinstance(notification_types, list):
            notification_types = [notification_types]

        for notification_type in [*notification_types]:
            if notification_type in UserNotificationUnsubscription.UNAVAILABLE_TYPES:
                notification_types.remove(notification_type)

        query = self.repo.user_notification_setting.get_unsubscriptions_query_builder(user)
        query = query.where_channel(channel).where_notification_type(notification_types)
        if scope == NotificationScope.Specific:
            if not model:
                return False
            query = query.where_scope(scope, model)
        else:
            query = query.where_scope(scope)

        unsubscriptions = query.all()
        already_unsubscribed_types = [unsubscription.notification_type for unsubscription in unsubscriptions]

        for notification_type in notification_types:
            if notification_type in already_unsubscribed_types:
                continue

            unsubscription = UserNotificationUnsubscription(
                user_id=user.id,
                channel=channel,
                notification_type=notification_type,
                scope_type=scope,
                specific_table=model.__tablename__ if model else None,
                specific_id=model.id if model else None,
            )

            self.repo.user_notification_setting.insert(unsubscription)

        return notification_types

    def has_unsubscription(
        self,
        user: User,
        notification_type: NotificationType,
        scope_models: list[tuple[str, int]] | None,
        channel: NotificationChannel,
    ) -> bool:
        query = (
            self.repo.user_notification_setting.get_unsubscriptions_query_builder(user)
            .where_channel(channel)
            .where_notification_type(notification_type)
        )
        unsubscription = query.where_scope(NotificationScope.All).first()
        if unsubscription:
            return True

        if not scope_models:
            return False

        for table_name, record_id in scope_models:
            unsubscription = query.where_scope(NotificationScope.Specific, (table_name, record_id)).first()
            if unsubscription:
                return True

        return False

    def toggle_all(self, user: User, channel: NotificationChannel, is_unsubscribed: bool) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": [notification_type for notification_type in NotificationType],
            "scope": NotificationScope.All,
        }

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)

    def toggle_type(
        self,
        user: User,
        channel: NotificationChannel,
        notification_type: NotificationType,
        is_unsubscribed: bool,
    ) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": notification_type,
            "scope": NotificationScope.All,
        }

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)

    @overload
    def toggle_project(
        self, user: User, channel: NotificationChannel, is_unsubscribed: bool
    ) -> list[NotificationType]: ...
    @overload
    def toggle_project(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam,
    ) -> list[NotificationType]: ...
    def toggle_project(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam | None = None,
    ) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": [
                NotificationType.AssignedToCard,
                NotificationType.MentionedInCard,
                NotificationType.MentionedInComment,
                NotificationType.MentionedInWiki,
                NotificationType.NotifiedFromChecklist,
                NotificationType.ReactedToComment,
            ],
        }

        if project:
            project = InfraHelper.get_by_id_like(Project, project)
            if not project:
                return []
            params["scope"] = NotificationScope.Specific
            params["model"] = project
        else:
            params["scope"] = NotificationScope.All

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)

    @overload
    def toggle_column(
        self, user: User, channel: NotificationChannel, is_unsubscribed: bool
    ) -> list[NotificationType]: ...
    @overload
    def toggle_column(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam,
        column: TColumnParam,
    ) -> list[NotificationType]: ...
    def toggle_column(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam | None = None,
        column: TColumnParam | None = None,
    ) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": [
                NotificationType.AssignedToCard,
                NotificationType.MentionedInCard,
                NotificationType.MentionedInComment,
                NotificationType.NotifiedFromChecklist,
                NotificationType.ReactedToComment,
            ],
        }

        if project and column:
            records = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
            if not records:
                return []
            project, column = records
            params["scope"] = NotificationScope.Specific
            params["model"] = column
        else:
            params["scope"] = NotificationScope.All

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)

    @overload
    def toggle_card(
        self, user: User, channel: NotificationChannel, is_unsubscribed: bool
    ) -> list[NotificationType]: ...
    @overload
    def toggle_card(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam,
        card: TCardParam,
    ) -> list[NotificationType]: ...
    def toggle_card(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam | None = None,
        card: TCardParam | None = None,
    ) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": [
                NotificationType.AssignedToCard,
                NotificationType.MentionedInCard,
                NotificationType.MentionedInComment,
                NotificationType.NotifiedFromChecklist,
                NotificationType.ReactedToComment,
            ],
        }

        if project and card:
            records = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
            if not records:
                return []
            project, card = records
            params["scope"] = NotificationScope.Specific
            params["model"] = card
        else:
            params["scope"] = NotificationScope.All

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)

    @overload
    def toggle_wiki(
        self, user: User, channel: NotificationChannel, is_unsubscribed: bool
    ) -> list[NotificationType]: ...
    @overload
    def toggle_wiki(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam,
        wiki: TWikiParam,
    ) -> list[NotificationType]: ...
    def toggle_wiki(
        self,
        user: User,
        channel: NotificationChannel,
        is_unsubscribed: bool,
        project: TProjectParam | None = None,
        wiki: TWikiParam | None = None,
    ) -> list[NotificationType]:
        params = {
            "user": user,
            "channel": channel,
            "notification_types": [NotificationType.MentionedInWiki],
        }

        if project and wiki:
            records = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
            if not records:
                return []
            project, wiki = records
            params["scope"] = NotificationScope.Specific
            params["model"] = wiki
        else:
            params["scope"] = NotificationScope.All

        if is_unsubscribed:
            return self.unsubscribe(**params)
        return self.subscribe(**params)
