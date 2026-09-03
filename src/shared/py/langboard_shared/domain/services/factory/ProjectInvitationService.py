from json import dumps as json_dumps
from typing import Any, Literal
from urllib.parse import urlparse
from ....core.domain import BaseDomainService
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....core.utils.String import concat, generate_random_string
from ....Env import UI_QUERY_NAMES, Env
from ....helpers import InfraHelper
from ....publishers import ProjectInvitationPublisher, ProjectPublisher
from ....tasks.activities import ProjectActivityTask, UserActivityTask
from ...models import Project, ProjectAssignedUser, ProjectInvitation, User, UserEmail
from .EmailService import EmailService
from .NotificationService import NotificationService
from .ProjectService import ProjectService


class InvitationRelatedResult:
    def __init__(self):
        self.already_assigned_ids: set[SnowflakeID] = set()
        self.already_sent_user_emails: set[str] = set()
        self.emails_should_invite: set[str] = set()
        self.emails_should_remove: dict[str, tuple[ProjectInvitation, User | None]] = {}
        self.users_by_email: dict[str, User] = {}
        self.user_ids_should_delete: set[SnowflakeID] = set()
        self.assigned_ids_should_delete: set[SnowflakeID] = set()


class ProjectInvitationService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project_invitation"

    def get_api_invited_user_list_by_project(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        if not project:
            return []
        raw_users = self.repo.project_invitation.get_all_by_project_with_user(project)

        users = []
        for invitation, invited_user in raw_users:
            users.append(
                invited_user.api_response()
                if invited_user
                else User.create_email_user_api_response(invitation.id, invitation.email)
            )

        return users

    def get_project_by_token(self, user: User, token: str) -> Project | None:
        invitation = self.__get_invitation_by_token(user, token)
        if not invitation:
            return None

        project = InfraHelper.get_by_id_like(Project, invitation.project_id)
        return project

    def get_invitation_related_data(self, project: Project, emails: list[str]) -> InvitationRelatedResult:
        invitations = self.repo.project_invitation.get_all_by_project(project)

        invitation_result = InvitationRelatedResult()

        for invitation in invitations:
            if invitation.email not in emails:
                user, subemail = self.repo.user.get_by_email(invitation.email)
                invitation_result.emails_should_remove[invitation.email] = (
                    invitation,
                    user,
                )

        for email in emails:
            user, subemail = self.repo.user.get_by_email(email)
            if user:
                invitation_result.emails_should_remove.pop(user.email, None)
            if subemail:
                invitation_result.emails_should_remove.pop(subemail.email, None)

            if user:
                assigned_user = self.repo.project_assigned_user.get_by_user_and_project(user, project)
                if assigned_user:
                    invitation_result.already_assigned_ids.add(assigned_user.id)
                    continue

            invitation = self.repo.project_invitation.get_by_project_and_email(project, email)
            if invitation:
                invitation_result.already_sent_user_emails.add(email)
            else:
                if user:
                    invitation_result.users_by_email[email] = user
                invitation_result.emails_should_invite.add(email)

        prev_assigned_users = InfraHelper.get_all_by(ProjectAssignedUser, "project_id", project.id)
        for assigned_user in prev_assigned_users:
            if assigned_user.user_id == project.owner_id:
                invitation_result.already_assigned_ids.add(assigned_user.id)
                continue

            if assigned_user.id not in invitation_result.already_assigned_ids:
                invitation_result.user_ids_should_delete.add(assigned_user.user_id)
                invitation_result.assigned_ids_should_delete.add(assigned_user.id)

        return invitation_result

    def get_additive_invitation_related_data(self, project: Project, emails: list[str]) -> InvitationRelatedResult:
        """Return only invitations that are not already assigned or pending."""

        invitation_result = InvitationRelatedResult()
        for email in emails:
            user, _ = self.repo.user.get_by_email(email)
            if user:
                assigned_user = self.repo.project_assigned_user.get_by_user_and_project(user, project)
                if assigned_user:
                    invitation_result.already_assigned_ids.add(assigned_user.id)
                    continue

            invitation = self.repo.project_invitation.get_by_project_and_email(project, email)
            if invitation:
                invitation_result.already_sent_user_emails.add(email)
                continue

            if user:
                invitation_result.users_by_email[email] = user
            invitation_result.emails_should_invite.add(email)

        return invitation_result

    def invite_emails(
        self, user: User, project: TProjectParam | None, invitation_result: InvitationRelatedResult
    ) -> bool:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False

        for email in invitation_result.emails_should_remove:
            invitation, target_user = invitation_result.emails_should_remove[email]
            if target_user:
                self.__delete_notification(target_user, project, invitation)
            self.repo.project_invitation.delete(invitation)

        email_service = self._get_service(EmailService)
        notification_service = self._get_service(NotificationService)
        for email in invitation_result.emails_should_invite:
            preferred_lang = user.preferred_lang
            target_user = invitation_result.users_by_email.get(email)
            if user.is_admin and target_user:
                self.__assign_project_user(project, target_user)
                continue

            invitation = ProjectInvitation(project_id=project.id, email=email, token=generate_random_string(32))
            self.repo.project_invitation.insert(invitation)

            if target_user:
                preferred_lang = target_user.preferred_lang
                notification_service.notify_project_invited(user, target_user, project, invitation)

            token_url = self.__create_invitation_token_url(invitation)
            email_service.send_template(
                preferred_lang,
                email,
                "project_invitation",
                {
                    "project_title": project.title,
                    "recipient": target_user.firstname if target_user else "there",
                    "sender": user.get_fullname(),
                    "url": token_url,
                },
            )

        return True

    def update_by_signed_up(self, user: User) -> None:
        invitations = self.repo.project_invitation.get_all_with_projects_by_email(user.email)
        if not invitations:
            return

        project_service = self._get_service(ProjectService)
        notification_service = self._get_service(NotificationService)
        invitation_map: dict[int, tuple[Project, list[ProjectInvitation]]] = {}
        for invitation, project in invitations:
            if project.id not in invitation_map:
                invitation_map[project.id] = project, []
            invitation_map[project.id][1].append(invitation)

        for project, project_invitations in invitation_map.values():
            owner = InfraHelper.get_by_id_like(User, project.owner_id)
            if owner:
                for invitation in project_invitations:
                    record_list = json_dumps(notification_service.create_record_list([project, invitation]))
                    existing_notification = self.repo.user_notification.get_project_invitation_notification(
                        user, record_list
                    )
                    if not existing_notification:
                        notification_service.notify_project_invited(owner, user, project, invitation)

            model = {
                "assigned_members": project_service.get_api_assigned_user_list(project),
                "invited_members": self.get_api_invited_user_list_by_project(project),
            }

            ProjectPublisher.assigned_users_updated(project, model)

    def accept(self, user: User, token: str) -> Literal[False] | str:
        invitation = self.__get_invitation_by_token(user, token)
        if not invitation:
            return False

        project = InfraHelper.get_by_id_like(Project, invitation.project_id)
        if not project:
            return False

        self.__assign_project_user(project, user, invitation)

        return project.get_uid()

    def decline(self, user: User, token: str) -> bool:
        invitation = self.__get_invitation_by_token(user, token)
        if not invitation:
            return False

        project = InfraHelper.get_by_id_like(Project, invitation.project_id)
        if not project:
            return False

        self.__delete_notification(user, project, invitation)

        self.repo.project_invitation.delete(invitation)

        UserActivityTask.declined_project_invitation(user, project)

        return True

    def __create_invitation_token_url(self, invitation: ProjectInvitation) -> str:
        encrypted_token = invitation.create_encrypted_token()

        url_chunks = urlparse(Env.UI_REDIRECT_URL)
        token_url = url_chunks._replace(
            query=concat(
                url_chunks.query,
                "&" if url_chunks.query else "",
                UI_QUERY_NAMES.PROJCT_INVITATION_TOKEN.value,
                "=",
                encrypted_token,
            )
        ).geturl()

        return token_url

    def __get_invitation_by_token(self, user: User, token: str) -> ProjectInvitation | None:
        invitation_token, invitation_id = ProjectInvitation.validate_token(token) or (
            None,
            None,
        )
        if not invitation_token or not invitation_id:
            return None

        invitation = self.repo.project_invitation.get_by_id_and_token(invitation_id, invitation_token)
        if not invitation:
            return None

        if user.email != invitation.email:
            subemail = InfraHelper.get_by(UserEmail, "email", invitation.email)
            if not subemail or subemail.user_id != user.id:
                return None

        return invitation

    def __assign_project_user(self, project: Project, user: User, invitation: ProjectInvitation | None = None):
        if invitation:
            self.__delete_notification(user, project, invitation)

            self.repo.project_invitation.delete(invitation)

        self.repo.project_assigned_user.ensure_assigned(project, user)
        project_users = self.repo.project_assigned_user.get_all_by_project(project)
        self.repo.project_user_relationship.ensure_project_relationships(
            project, [assigned_user.id for assigned_user, _ in project_users]
        )
        self.repo.role.project.grant_default(user_id=user.id, project_id=project.id)
        ProjectPublisher.assigned_to_users(project, [user])

        project_service = self._get_service(ProjectService)

        model: dict[str, Any] = {
            "assigned_members": project_service.get_api_assigned_user_list(project),
            "invited_members": self.get_api_invited_user_list_by_project(project),
        }

        if invitation:
            model["invitation_uid"] = invitation.get_uid()

        ProjectInvitationPublisher.accepted(project, model)

        ProjectActivityTask.project_invited_user_accepted(user, project)

    def __delete_notification(self, user: User, project: Project, invitation: ProjectInvitation):
        notification_service = self._get_service(NotificationService)
        record_list = json_dumps(notification_service.create_record_list([project, invitation]))
        notification = self.repo.user_notification.get_project_invitation_notification(user, record_list)
        if not notification:
            return

        self.repo.user_notification.delete(notification)

        ProjectInvitationPublisher.notification_deleted(user, notification)
