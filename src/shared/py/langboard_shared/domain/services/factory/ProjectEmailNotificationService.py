from dataclasses import dataclass
from html import escape
from typing import Any, cast
from urllib.parse import urlparse
from pydantic import EmailStr, TypeAdapter, ValidationError
from ....core.domain import BaseDomainService
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....core.utils.String import concat
from ....Env import UI_QUERY_NAMES, Env
from ....helpers import InfraHelper
from ....tasks.activities import ProjectActivityTask
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


@dataclass(frozen=True)
class ProjectEmailDeliveryRecipient:
    """One policy-authorized delivery target resolved at execution time."""

    email: str
    language: str


_EMAIL_ADAPTER = TypeAdapter(EmailStr)


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
            "external_recipient_emails": policy.external_recipient_emails if policy else [],
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
            "last_delivery_status": policy.last_delivery_status if policy else None,
            "last_delivery_at": policy.last_delivery_at if policy else None,
            "last_delivery_recipient_email": policy.last_delivery_recipient_email if policy else None,
            "last_delivery_error": policy.last_delivery_error if policy else None,
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
        external_recipient_emails: list[str],
        actor: User | None = None,
    ) -> dict[str, Any] | None:
        """Replace one board policy after checking every recipient is a current member."""

        project_model = InfraHelper.get_by_id_like(Project, project)
        if not project_model:
            return None
        existing_policy, _ = self.repo.project_email_notification.get_with_recipients(project_model)
        if len(categories) != len(set(categories)):
            raise ValueError("Email notification categories must be unique")
        if len(recipient_user_uids) != len(set(recipient_user_uids)):
            raise ValueError("Email notification recipients must be unique")
        if len(recipient_user_uids) > 50:
            raise ValueError("Email notification recipients are limited to 50")
        normalized_external_emails = self._normalize_external_emails(external_recipient_emails)
        if len(normalized_external_emails) > 50:
            raise ValueError("External email notification recipients are limited to 50")
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
        if is_enabled and (
            not categories
            or (not notify_all_members and not recipient_user_uids and not normalized_external_emails)
        ):
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
            external_recipient_emails=normalized_external_emails,
        )
        previous_external_emails = set(existing_policy.external_recipient_emails if existing_policy else [])
        current_external_emails = set(normalized_external_emails)
        if actor and previous_external_emails != current_external_emails:
            ProjectActivityTask.project_email_notification_policy_updated(
                actor,
                project_model,
                sorted(current_external_emails - previous_external_emails),
                sorted(previous_external_emails - current_external_emails),
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
                "external_recipient_emails": normalized_external_emails,
            }
        )
        return response

    def get_delivery_recipients(
        self,
        activity: ProjectActivity | ProjectWikiActivity,
    ) -> list[ProjectEmailDeliveryRecipient]:
        """Return deduplicated current members and explicit edge email recipients."""

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

        actor = cast(User | None, InfraHelper.get_by_id_like(User, activity.user_id)) if activity.user_id else None
        actor_email = actor.email.casefold() if actor and actor.email else None
        resolved: dict[str, ProjectEmailDeliveryRecipient] = {}
        for recipient in recipients:
            if (
                recipient.id == activity.user_id
                or recipient.deleted_at is not None
                or recipient.activated_at is None
                or not recipient.email
            ):
                continue
            email = recipient.email.casefold()
            if email != actor_email:
                resolved[email] = ProjectEmailDeliveryRecipient(email=email, language=recipient.preferred_lang)
        for email in policy.external_recipient_emails:
            normalized = email.casefold()
            if normalized != actor_email:
                resolved.setdefault(normalized, ProjectEmailDeliveryRecipient(email=normalized, language="en-US"))
        return list(resolved.values())

    def send_activity_email(
        self,
        activity: ProjectActivity | ProjectWikiActivity,
        recipient_email: str,
    ) -> bool:
        """Send one policy-authorized activity email through the existing SMTP service."""

        recipient = next(
            (item for item in self.get_delivery_recipients(activity) if item.email == recipient_email.casefold()),
            None,
        )
        if recipient is None:
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
            recipient.language,
            recipient.email,
            "project_activity_updated",
            {
                "sender": escape(notifier.get_fullname() if isinstance(notifier, User) else notifier.name),
                "project_name": escape(project.title),
                "activity_name": escape(action_name),
                "target_name": escape(target_name),
                "url": self._create_redirect_url(project, activity),
            },
            reply_to=self._project_owner_email(project),
        )

    def record_delivery(
        self,
        activity: ProjectActivity | ProjectWikiActivity,
        recipient_email: str,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> None:
        """Persist the latest delivery outcome without storing message content."""

        self.repo.project_email_notification.record_delivery(
            activity.project_id,
            recipient_email=recipient_email.casefold(),
            succeeded=succeeded,
            error=error,
        )

    @staticmethod
    def smtp_available() -> bool:
        """Report whether the existing SMTP transport has its required public configuration."""

        return bool(Env.MAIL_SERVER and Env.MAIL_FROM and Env.MAIL_PORT)

    @staticmethod
    def _normalize_external_emails(emails: list[str]) -> list[str]:
        """Validate, normalize, and deduplicate explicit edge recipients."""

        normalized: list[str] = []
        for raw_email in emails:
            try:
                email = str(_EMAIL_ADAPTER.validate_python(raw_email.strip())).casefold()
            except (ValidationError, ValueError) as exc:
                raise ValueError("Every external email notification recipient must be valid") from exc
            if email not in normalized:
                normalized.append(email)
        return normalized

    @staticmethod
    def _project_owner_email(project: Project) -> str | None:
        """Resolve Reply-To from the board owner instead of another mutable setting."""

        owner = cast(User | None, InfraHelper.get_by_id_like(User, project.owner_id))
        return owner.email if owner and owner.email else None

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
