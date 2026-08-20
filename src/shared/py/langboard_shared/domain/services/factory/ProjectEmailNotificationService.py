from html import escape
from typing import Any, cast
from urllib.parse import urlparse
from ....core.domain import BaseDomainService
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....core.utils.String import concat
from ....Env import UI_QUERY_NAMES, Env
from ....helpers import InfraHelper
from ...models import Bot, Project, ProjectActivity, ProjectWikiActivity, User
from ...models.ProjectActivity import ProjectActivityType
from ...models.ProjectEmailNotificationPolicy import (
    ProjectEmailNotificationCategory,
    ProjectEmailNotificationPolicy,
)
from ...models.ProjectWikiActivity import ProjectWikiActivityType
from .EmailService import EmailService


_ACTIVITY_CATEGORY: dict[str, ProjectEmailNotificationCategory] = {
    **{
        activity_type.value: ProjectEmailNotificationCategory.Board
        for activity_type in (
            ProjectActivityType.ProjectCreated,
            ProjectActivityType.ProjectUpdated,
            ProjectActivityType.ProjectAssignedUsersUpdated,
            ProjectActivityType.ProjectInvitedUserAccepted,
            ProjectActivityType.ProjectDeleted,
            ProjectActivityType.ProjectColumnCreated,
            ProjectActivityType.ProjectColumnNameChanged,
            ProjectActivityType.ProjectColumnDeleted,
            ProjectActivityType.ProjectLabelCreated,
            ProjectActivityType.ProjectLabelUpdated,
            ProjectActivityType.ProjectLabelDeleted,
        )
    },
    **{
        activity_type.value: ProjectEmailNotificationCategory.Cards
        for activity_type in (
            ProjectActivityType.CardCreated,
            ProjectActivityType.CardUpdated,
            ProjectActivityType.CardMoved,
            ProjectActivityType.CardAssignedUsersUpdated,
            ProjectActivityType.CardLabelsUpdated,
            ProjectActivityType.CardDeleted,
            ProjectActivityType.CardRelationshipsUpdated,
        )
    },
    **{
        activity_type.value: ProjectEmailNotificationCategory.Comments
        for activity_type in (
            ProjectActivityType.CardCommentAdded,
            ProjectActivityType.CardCommentUpdated,
            ProjectActivityType.CardCommentDeleted,
            ProjectActivityType.CardCommentReacted,
            ProjectActivityType.CardCommentUnreacted,
        )
    },
    **{
        activity_type.value: ProjectEmailNotificationCategory.Attachments
        for activity_type in (
            ProjectActivityType.CardAttachmentUploaded,
            ProjectActivityType.CardAttachmentNameChanged,
            ProjectActivityType.CardAttachmentDeleted,
        )
    },
    **{
        activity_type.value: ProjectEmailNotificationCategory.Checklists
        for activity_type in ProjectActivityType
        if activity_type.value.startswith("card_checklist_") or activity_type.value.startswith("card_checkitem_")
    },
    **{activity_type.value: ProjectEmailNotificationCategory.Wiki for activity_type in ProjectWikiActivityType},
}


class ProjectEmailNotificationService(BaseDomainService):
    DEFAULT_CATEGORIES = [
        ProjectEmailNotificationCategory.Cards,
        ProjectEmailNotificationCategory.Comments,
    ]

    @staticmethod
    def name() -> str:
        """Return the factory key."""

        return "project_email_notification"

    def get_api_policy(self, project: TProjectParam) -> dict[str, Any] | None:
        """Return one board policy and the current eligible member list."""

        project_model = InfraHelper.get_by_id_like(Project, project)
        if not project_model:
            return None

        policy, recipients = self.repo.project_email_notification.get_with_recipients(project_model)
        members = self.repo.project_assigned_user.get_all_by_project(project_model)
        columns = [
            column
            for column, _ in self.repo.project_column.get_all_by_project(project_model)
            if not column.is_archive
        ]
        return {
            "is_enabled": policy.is_enabled if policy else False,
            "notify_all_members": policy.notify_all_members if policy else False,
            "categories": [category.value for category in (policy.categories if policy else self.DEFAULT_CATEGORIES)],
            "card_move_target_columns": policy.card_move_target_columns if policy else [],
            "recipient_user_uids": [recipient.get_uid() for recipient in recipients],
            "available_recipients": [
                {
                    "uid": member.get_uid(),
                    "firstname": member.firstname,
                    "lastname": member.lastname,
                    "email": member.email,
                }
                for member, _ in members
                if member.deleted_at is None and member.activated_at is not None and bool(member.email)
            ],
            "available_columns": [column.name for column in sorted(columns, key=lambda item: item.order)],
            "smtp_available": self.smtp_available(),
        }

    def update_policy(
        self,
        project: TProjectParam,
        *,
        is_enabled: bool,
        notify_all_members: bool,
        categories: list[ProjectEmailNotificationCategory],
        recipient_user_uids: list[str],
        card_move_target_columns: list[str],
    ) -> dict[str, Any] | None:
        """Replace one board policy after checking every recipient is a current member."""

        project_model = InfraHelper.get_by_id_like(Project, project)
        if not project_model:
            return None
        if len(categories) != len(set(categories)):
            raise ValueError("Email notification categories must be unique")
        if len(recipient_user_uids) != len(set(recipient_user_uids)):
            raise ValueError("Email notification recipients must be unique")
        if len(recipient_user_uids) > 50:
            raise ValueError("Email notification recipients are limited to 50")
        normalized_columns = [column.strip() for column in card_move_target_columns if column.strip()]
        if len(normalized_columns) != len(set(normalized_columns)):
            raise ValueError("Card move target columns must be unique")
        project_columns = {
            column.name
            for column, _ in self.repo.project_column.get_all_by_project(project_model)
            if not column.is_archive
        }
        if not set(normalized_columns).issubset(project_columns):
            raise ValueError("Every card move target column must exist on the project")
        if is_enabled and (not categories or (not notify_all_members and not recipient_user_uids)):
            raise ValueError("Enabled email notifications require a category and recipient")

        recipient_ids = [SnowflakeID.from_short_code(uid) for uid in recipient_user_uids]
        members = self.repo.project_assigned_user.get_all_by_project(project_model, recipient_ids)
        eligible_members = {
            member.id: member
            for member, _ in members
            if member.deleted_at is None and member.activated_at is not None and member.email
        }
        if set(recipient_ids) != set(eligible_members):
            raise ValueError("Every email notification recipient must be an active project member")

        self.repo.project_email_notification.replace(
            project_model,
            is_enabled=is_enabled,
            notify_all_members=notify_all_members,
            categories=categories,
            card_move_target_columns=normalized_columns,
            recipient_user_ids=recipient_ids,
        )
        response = self.get_api_policy(project_model)
        if response is None:
            return None
        response.update(
            {
                "is_enabled": is_enabled,
                "notify_all_members": notify_all_members,
                "categories": [category.value for category in categories],
                "card_move_target_columns": normalized_columns,
                "recipient_user_uids": [eligible_members[user_id].get_uid() for user_id in recipient_ids],
            }
        )
        return response

    def get_delivery_recipient_ids(
        self,
        activity: ProjectActivity | ProjectWikiActivity,
    ) -> list[SnowflakeID]:
        """Return current eligible recipients for one persisted board activity."""

        category = self.category_for_activity(activity.activity_type.value)
        if category is None:
            return []
        policy, recipients = self.repo.project_email_notification.get_with_recipients(activity.project_id)
        if not policy or not policy.is_enabled or category not in policy.categories:
            return []
        if not self._matches_card_move_target(activity, policy):
            return []

        if policy.notify_all_members:
            recipients = [member for member, _ in self.repo.project_assigned_user.get_all_by_project(activity.project_id)]
        else:
            recipient_ids = [recipient.id for recipient in recipients]
            current_members = self.repo.project_assigned_user.get_all_by_project(activity.project_id, recipient_ids)
            current_member_ids = {member.id for member, _ in current_members}
            recipients = [recipient for recipient in recipients if recipient.id in current_member_ids]

        actor_id = activity.user_id
        return [
            recipient.id
            for recipient in recipients
            if recipient.id != actor_id
            and recipient.deleted_at is None
            and recipient.activated_at is not None
            and bool(recipient.email)
        ]

    def send_activity_email(
        self,
        activity: ProjectActivity | ProjectWikiActivity,
        recipient: User,
    ) -> bool:
        """Send one policy-authorized activity email through the existing SMTP service."""

        if recipient.id not in self.get_delivery_recipient_ids(activity):
            return True
        project = cast(Project | None, InfraHelper.get_by_id_like(Project, activity.project_id))
        if not project:
            return True
        notifier = self._get_activity_notifier(activity)
        if not notifier:
            return True

        history = activity.activity_history
        target_name = self._activity_target_name(history, project.title)
        action_name = activity.activity_type.value.replace("_", " ").capitalize()
        return self._get_service(EmailService).send_template(
            recipient.preferred_lang,
            recipient.email,
            "project_activity_updated",
            {
                "recipient": escape(recipient.firstname),
                "sender": escape(notifier.get_fullname() if isinstance(notifier, User) else notifier.name),
                "project_name": escape(project.title),
                "activity_name": escape(action_name),
                "target_name": escape(target_name),
                "url": self._create_redirect_url(project, activity),
            },
        )

    @staticmethod
    def smtp_available() -> bool:
        """Report whether the existing SMTP transport has its required public configuration."""

        return bool(Env.MAIL_SERVER and Env.MAIL_FROM and Env.MAIL_PORT)

    @staticmethod
    def category_for_activity(activity_type: str) -> ProjectEmailNotificationCategory | None:
        """Map one native activity fact to a board policy category."""

        return _ACTIVITY_CATEGORY.get(activity_type)

    @staticmethod
    def _matches_card_move_target(
        activity: ProjectActivity | ProjectWikiActivity,
        policy: ProjectEmailNotificationPolicy,
    ) -> bool:
        """Apply an optional target-column gate without turning it into a rule engine."""

        if not policy.card_move_target_columns:
            return True
        if not isinstance(activity, ProjectActivity) or activity.activity_type != ProjectActivityType.CardMoved:
            return False
        column = activity.activity_history.get("column")
        return isinstance(column, dict) and column.get("name") in policy.card_move_target_columns

    @staticmethod
    def _activity_target_name(history: dict[str, Any], fallback: str) -> str:
        for key in ("card", "wiki", "checklist", "checkitem", "attachment", "column", "label", "project"):
            value = history.get(key)
            if not isinstance(value, dict):
                continue
            for field in ("title", "name"):
                label = value.get(field)
                if isinstance(label, str) and label.strip():
                    return label.strip()
        return fallback

    @staticmethod
    def _get_activity_notifier(activity: ProjectActivity | ProjectWikiActivity) -> User | Bot | None:
        model = User if activity.user_id else Bot
        identifier = activity.user_id or activity.bot_id
        return cast(User | Bot | None, InfraHelper.get_by_id_like(model, identifier, with_deleted=True))

    @staticmethod
    def _create_redirect_url(project: Project, activity: ProjectActivity | ProjectWikiActivity) -> str:
        chunks = urlparse(Env.UI_REDIRECT_URL)
        query = concat(UI_QUERY_NAMES.BOARD.value, "=", project.get_uid())
        if isinstance(activity, ProjectActivity) and activity.card_id:
            query = concat(
                UI_QUERY_NAMES.BOARD_CARD_CHUNK.value,
                "=",
                project.get_uid(),
                "&",
                UI_QUERY_NAMES.BOARD_CARD.value,
                "=",
                activity.card_id.to_short_code(),
            )
        elif isinstance(activity, ProjectWikiActivity):
            query = concat(
                UI_QUERY_NAMES.BOARD_WIKI_CHUNK.value,
                "=",
                project.get_uid(),
                "&",
                UI_QUERY_NAMES.BOARD_WIKI.value,
                "=",
                activity.project_wiki_id.to_short_code(),
            )
        return chunks._replace(query=concat(chunks.query, "&" if chunks.query else "", query)).geturl()
