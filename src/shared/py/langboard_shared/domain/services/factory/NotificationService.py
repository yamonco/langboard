from typing import Any, Literal, TypeVar, cast, overload
from urllib.parse import urlparse
from ....core.db import BaseDbModel, EditorContentModel
from ....core.domain import BaseDomainService
from ....core.publisher import NotificationPublisher, NotificationPublishModel
from ....core.resources.locales.EmailTemplateNames import TEmailTemplateName
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TNotificationParam, TUserOrBot, TUserParam
from ....core.utils.EditorContentParser import change_date_element, find_mentioned
from ....core.utils.String import concat
from ....Env import UI_QUERY_NAMES, Env
from ....helpers import InfraHelper
from ....tasks.bots import BotDefaultTask
from ...models import (
    Bot,
    Card,
    CardComment,
    Checkitem,
    Checklist,
    Project,
    ProjectColumn,
    ProjectInvitation,
    ProjectWiki,
    User,
    UserNotification,
)
from ...models.BaseNotificationScheduleModel import BaseNotificationScheduleModel
from ...models.UserNotification import NotificationType


_TModel = TypeVar(
    "_TModel",
    bound=User | Bot | Project | ProjectInvitation | ProjectWiki | Card | CardComment | Checklist | Checkitem,
)


class NotificationService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "notification"

    def get_api_list(
        self,
        user: User,
        time_range: Literal["3d", "7d", "1m", "all"] = "3d",
        page: int = 1,
        limit: int = 20,
        unread_only: bool = False,
    ) -> tuple[list[dict[str, Any]], bool, int]:
        """Return one notification page, optionally limited to unread rows."""

        raw_notifications = self.repo.user_notification.get_list(user, time_range, page, limit, unread_only)
        has_more = len(raw_notifications) > limit
        raw_notifications = raw_notifications[:limit]
        unread_count = self.repo.user_notification.count_unread(user)

        references: list[tuple[str, int]] = []
        for notification in raw_notifications:
            references.append((notification.notifier_type, notification.notifier_id))
            for table_name, record_id in notification.record_list:
                references.append((table_name, record_id))
        cached_dict = InfraHelper.get_references(references, as_type="notification")

        notifications = []
        notification_ids_should_delete = []
        for notification in raw_notifications:
            notification_records = {}
            should_continue = True
            for table_name, record_id in notification.record_list:
                record = cached_dict.get(f"{table_name}_{record_id}")
                if not record:
                    should_continue = False
                    break
                notification_records[table_name] = record
            if not should_continue:
                notification_ids_should_delete.append(notification.id)
                continue

            notifier_cache_key = f"{notification.notifier_type}_{notification.notifier_id}"
            notifier_key = f"notifier_{notification.notifier_type}"
            notifier = cached_dict.get(notifier_cache_key)
            if not notifier:
                continue

            notifications.append(
                {
                    **notification.api_response(),
                    notifier_key: notifier,
                    "records": notification_records,
                }
            )

        if notification_ids_should_delete and not unread_only:
            self.repo.user_notification.delete_all_by_ids(notification_ids_should_delete)

        return notifications, has_more, unread_count

    def convert_to_api_response(
        self,
        notification: UserNotification,
        record_list: list[_TModel] | None = None,
        notifier: TUserOrBot | None = None,
    ) -> dict[str, Any]:
        api_notification = notification.api_response()
        table_ids_dict = InfraHelper.combine_table_with_ids(notification.record_list)

        records: dict[str, Any] = {}
        if record_list:
            for record in record_list:
                table_name = type(record).__tablename__
                if table_name not in records:
                    records[table_name] = {}
                records[table_name] = record.notification_data()
        else:
            for table_name, record_ids in table_ids_dict.items():
                results = InfraHelper.get_records_by_table_name_with_ids(table_name, record_ids)
                if not results:
                    continue
                for record in results:
                    if table_name not in records:
                        records[table_name] = {}
                    records[table_name] = record.notification_data()

        api_notification["records"] = records
        if notifier:
            notifier_key, api_notifier = (
                "notifier_user" if isinstance(notifier, User) else "notifier_bot",
                notifier.api_response(),
            )
        else:
            notifier_key, api_notifier = self.get_notifier(notification, as_api=True)
        api_notification[notifier_key] = api_notifier
        return api_notification

    @overload
    def get_notifier(self, notification: UserNotification, as_api: Literal[False]) -> User | Bot: ...
    @overload
    def get_notifier(self, notification: UserNotification, as_api: Literal[True]) -> tuple[str, dict[str, Any]]: ...
    def get_notifier(self, notification: UserNotification, as_api: bool) -> User | Bot | tuple[str, dict[str, Any]]:
        if notification.notifier_type == "user":
            notifier = cast(
                User,
                InfraHelper.get_by(User, "id", notification.notifier_id, with_deleted=True),
            )
        else:
            notifier = cast(
                Bot,
                InfraHelper.get_by(Bot, "id", notification.notifier_id, with_deleted=True),
            )

        if not as_api:
            return notifier

        if notification.notifier_type == "user":
            return "notifier_user", notifier.api_response()
        return "notifier_bot", notifier.api_response()

    def read(self, user: User, notification: TNotificationParam | None) -> bool:
        notification = InfraHelper.get_by_id_like(UserNotification, notification)
        if not notification or notification.receiver_id != user.id:
            return False

        notification.read_at = SafeDateTime.now()
        self.repo.user_notification.update(notification)

        return True

    def read_all(self, user: User):
        self.repo.user_notification.read_all_by_user(user)

    def delete(self, user: User, notification: TNotificationParam | None) -> bool:
        notification = InfraHelper.get_by_id_like(UserNotification, notification)
        if not notification or notification.receiver_id != user.id:
            return False

        self.repo.user_notification.delete(notification)

        return True

    def delete_all(self, user: User):
        self.repo.user_notification.delete_all(user)

    # from here, notifiable types are added
    def notify_project_invited(
        self,
        notifier: TUserOrBot,
        target_user: TUserParam | None,
        project: Project,
        project_invitation: ProjectInvitation,
    ):
        self.__notify(
            notifier,
            target_user,
            NotificationType.ProjectInvited,
            None,
            [project, project_invitation],
        )

    def notify_mentioned_in_card(self, notifier: TUserOrBot, project: Project, card: Card):
        column = self.__get_column_by_card(card)
        self.__notify_mentioned(
            notifier,
            card.description,
            NotificationType.MentionedInCard,
            [project, column, card],
            [project, card],
            "mentioned_in_card",
            {"url": self.__create_redirect_url(project, card)},
        )

    def notify_mentioned_in_comment(self, notifier: TUserOrBot, project: Project, card: Card, comment: CardComment):
        column = self.__get_column_by_card(card)
        self.__notify_mentioned(
            notifier,
            comment.content,
            NotificationType.MentionedInComment,
            [project, column, card],
            [project, card, comment],
            "mentioned_in_comment",
            {"url": self.__create_redirect_url(project, card)},
        )

    def notify_mentioned_in_wiki(self, notifier: TUserOrBot, project: Project, wiki: ProjectWiki):
        self.__notify_mentioned(
            notifier,
            wiki.content,
            NotificationType.MentionedInWiki,
            [project, wiki],
            [project, wiki],
            "mentioned_in_wiki",
            {"url": self.__create_redirect_url(project, wiki)},
        )

    def notify_assigned_to_card(
        self,
        notifier: TUserOrBot,
        target_user: TUserParam | None,
        project: Project,
        card: Card,
    ):
        column = self.__get_column_by_card(card)
        self.__notify(
            notifier,
            target_user,
            NotificationType.AssignedToCard,
            [project, column, card],
            [project, card],
            {},
            "assigned_to_card",
            {"url": self.__create_redirect_url(project, card)},
        )

    def notify_reacted_to_comment(
        self,
        notifier: TUserOrBot,
        project: Project,
        card: Card,
        comment: CardComment,
        reaction_type: str,
    ):
        column = self.__get_column_by_card(card)
        first_line = ""
        if comment.content:
            content = change_date_element(comment.content).strip().splitlines()
            first_line = content.pop() if content else ""
        self.__notify(
            notifier,
            cast(int, comment.user_id),
            NotificationType.ReactedToComment,
            [project, column, card],
            [project, card, comment],
            {"reaction_type": reaction_type, "line": first_line},
            "reacted_to_comment",
            {"url": self.__create_redirect_url(project, card)},
        )

    def notify_checklist(
        self,
        notifier: TUserOrBot,
        target_user: TUserParam | None,
        project: Project,
        card: Card,
        checklist: Checklist,
    ):
        column = self.__get_column_by_card(card)
        self.__notify(
            notifier,
            target_user,
            NotificationType.NotifiedFromChecklist,
            [project, column, card],
            [project, card, checklist],
            None,
            "notified_from_checklist",
            {"url": self.__create_redirect_url(project, card)},
        )

    def notify_notification_schedule_rule(
        self,
        notifier: TUserOrBot,
        target_user: TUserParam | None,
        notification_type: NotificationType,
        project: Project,
        rule_name: str,
        target_model: BaseNotificationScheduleModel,
        message_vars: dict[str, Any],
        now: SafeDateTime,
    ) -> bool:
        references: list = [project]
        scope_models: list[BaseDbModel] = [project]
        if isinstance(target_model, Card):
            column = self.__get_column_by_card(target_model)
            references.append(target_model)
            scope_models.extend([column, target_model])
        elif isinstance(target_model, Checkitem):
            card = self.__get_card_by_checkitem(target_model)
            column = self.__get_column_by_card(card)
            references.extend([card, target_model])
            scope_models.extend([column, card, target_model])

        target_message_vars = target_model.get_notification_schedule_rule_message_vars(
            str(message_vars.get("field") or ""),
            str(message_vars.get("operator") or ""),
            now,
        )
        if target_message_vars is None:
            return False

        return self.__notify(
            notifier,
            target_user,
            notification_type,
            scope_models,
            references,
            {
                **message_vars,
                **target_message_vars,
                "rule_name": rule_name,
            },
            allow_self=True,
        )

    def create_record_list(self, record_list: list[_TModel]) -> list[tuple[str, SnowflakeID]]:
        return [(type(record).__tablename__, record.id) for record in record_list]

    # to here, notifiable types are added

    def __notify_mentioned(
        self,
        notifier: TUserOrBot,
        editor: EditorContentModel | None,
        notification_type: NotificationType,
        scope_models: list[BaseDbModel],
        references: list[_TModel],
        email_template_name: TEmailTemplateName,
        email_formats: dict[str, str],
    ):
        if not editor or not editor.content:
            return
        user_or_bot_uids, mentioned_lines = find_mentioned(editor)
        mentioned_in = ""
        other_models: list[BaseDbModel] = []
        if email_template_name == "mentioned_in_card":
            mentioned_in = "card"
        elif email_template_name == "mentioned_in_comment":
            mentioned_in = "comment"
            other_models = [references[-1]]
        elif email_template_name == "mentioned_in_wiki":
            mentioned_in = "project_wiki"

        for user_or_bot_uid in user_or_bot_uids:
            result = self.__notify(
                notifier,
                user_or_bot_uid,
                notification_type,
                scope_models,
                references,
                {"line": mentioned_lines[user_or_bot_uid]},
                email_template_name,
                email_formats,
            )

            if result or not mentioned_in:
                continue

            target_bot = InfraHelper.get_by_id_like(Bot, user_or_bot_uid)
            if not target_bot or target_bot.id == notifier.id:
                continue

            models = [*scope_models, *other_models]
            dumped_models: list[tuple[str, dict]] = []
            for model in models:
                dumped_models.append((type(model).__tablename__, model.model_dump()))
            BotDefaultTask.bot_mentioned(notifier, target_bot, mentioned_in, dumped_models)

    def __notify(
        self,
        notifier: TUserOrBot,
        target_user: TUserParam | None,
        notification_type: NotificationType,
        scope_models: list[BaseDbModel] | None,
        references: list[_TModel],
        message_vars: dict[str, Any] | None = None,
        email_template_name: TEmailTemplateName | None = None,
        email_formats: dict[str, str] | None = None,
        allow_self: bool = False,
    ) -> bool:
        target_user = InfraHelper.get_by_id_like(User, target_user)
        if not target_user or (target_user.id == notifier.id and not allow_self):
            return False

        raw_record_list = self.create_record_list(references)
        record_list = [(table_name, SnowflakeID(record_id)) for table_name, record_id in raw_record_list]

        scope_model_tuples = (
            [(type(scope_model).__tablename__, int(scope_model.id)) for scope_model in scope_models]
            if scope_models
            else None
        )

        if email_formats:
            email_formats["recipient"] = target_user.firstname
            email_formats["sender"] = notifier.get_fullname()

        notification = UserNotification(
            id=SnowflakeID(),  # generate new ID
            notifier_type="user" if isinstance(notifier, User) else "bot",
            notifier_id=notifier.id,
            receiver_id=target_user.id,
            notification_type=notification_type,
            message_vars=message_vars or {},
            record_list=record_list,
        )

        model = NotificationPublishModel(
            notification=notification,
            api_notification=self.convert_to_api_response(notification, references, notifier),
            target_user=target_user,
            scope_models=scope_model_tuples,
            email_template_name=email_template_name,
            email_formats=email_formats,
        )
        NotificationPublisher.put_dispather(model)
        return True

    def __create_redirect_url(self, project: Project, card_or_wiki: ProjectWiki | Card | None = None):
        url_chunks = urlparse(Env.UI_REDIRECT_URL)
        query_string = ""
        if card_or_wiki:
            chunk_query = (
                UI_QUERY_NAMES.BOARD_CARD_CHUNK if isinstance(card_or_wiki, Card) else UI_QUERY_NAMES.BOARD_WIKI_CHUNK
            )
            main_query = UI_QUERY_NAMES.BOARD_CARD if isinstance(card_or_wiki, Card) else UI_QUERY_NAMES.BOARD_WIKI
            query_string = concat(
                chunk_query.value,
                "=",
                project.get_uid(),
                "&",
                main_query.value,
                "=",
                card_or_wiki.get_uid(),
            )
        else:
            query_string = concat(UI_QUERY_NAMES.BOARD.value, "=", project.get_uid())
        url = url_chunks._replace(
            query=concat(
                url_chunks.query,
                "&" if url_chunks.query else "",
                query_string,
            )
        ).geturl()

        return url

    def __get_column_by_card(self, card: Card):
        column = InfraHelper.get_by_id_like(ProjectColumn, card.project_column_id)
        return cast(ProjectColumn, column)

    def __get_card_by_checkitem(self, checkitem: Checkitem):
        checklist = InfraHelper.get_by_id_like(Checklist, checkitem.checklist_id)
        return cast(Card, InfraHelper.get_by_id_like(Card, checklist.card_id if checklist else None))
