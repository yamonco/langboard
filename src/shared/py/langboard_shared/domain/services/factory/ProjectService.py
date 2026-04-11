from typing import TYPE_CHECKING, Any, Literal, cast
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TInternalBotParam, TProjectParam, TUserOrBot, TUserParam
from ....core.utils.Converter import convert_python_data
from ....helpers import InfraHelper
from ....publishers import ProjectPublisher
from ....tasks.activities import ProjectActivityTask
from ....tasks.bots import ProjectBotTask
from ...models import (
    InternalBot,
    Project,
    ProjectAssignedInternalBot,
    ProjectAssignedUser,
    ProjectBotSchedule,
    ProjectBotScope,
    ProjectRole,
    User,
)
from ...models.bases import ALL_GRANTED
from ...models.Checkitem import CheckitemStatus
from ...models.InternalBot import InternalBotType
from ...models.ProjectRole import ProjectRoleAction
from .CheckitemService import CheckitemService
from .ProjectColumnService import ProjectColumnService
from .ProjectLabelService import ProjectLabelService


if TYPE_CHECKING:
    from .ProjectInvitationService import ProjectInvitationService


class ProjectService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project"

    def get_by_id_like(self, project: TProjectParam | None) -> Project | None:
        project = InfraHelper.get_by_id_like(Project, project)
        return project

    def get_api_list(self, user: User) -> tuple[list[dict[str, Any]], list[SnowflakeID]]:
        raw_projects = self.repo.project.get_all_by_user(user)

        projects = []
        all_roles = self.get_all_roles(user)
        roles_dict = {}

        if not user.is_admin:
            for role in all_roles:
                if role.project_id in roles_dict:
                    continue
                roles_dict[role.project_id] = role.actions

        project_ids = []
        for project, assigned_user in raw_projects:
            if not user.is_admin and project.id not in roles_dict:
                continue

            project_ids.append(project.id)

            api_project = project.api_response()
            api_project["starred"] = assigned_user.starred
            api_project["last_viewed_at"] = assigned_user.last_viewed_at
            api_project["current_auth_role_actions"] = roles_dict[project.id] if not user.is_admin else [ALL_GRANTED]
            projects.append(api_project)

        return projects, project_ids

    def get_api_assigned_user_list(
        self, project: TProjectParam | None, where_user_in: list[TUserParam] | None = None
    ) -> list[dict[str, Any]]:
        if not project:
            return []

        raw_users = self.repo.project_assigned_user.get_all_by_project(project, where_users_in=where_user_in)

        users = [user.api_response() for user, _ in raw_users]
        return users

    def get_user_role_actions_by_project(self, user: User, project: Project) -> list[str]:
        if user.is_admin:
            return [ALL_GRANTED]
        role = self.repo.role.project.get_one(user_id=user.id, project_id=project.id)
        return role.actions if role else []

    def get_all_roles(self, user: User) -> list[ProjectRole]:
        roles = self.repo.role.project.get_list(user_id=user.id)
        return roles

    def get_api_assigned_internal_bot_list_with_setting_map(
        self, project: TProjectParam | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return [], {}

        raw_internal_bots = self.repo.project_assigned_internal_bot.get_all_by_project(project)

        internal_bots = []
        internal_bot_settings = {}
        for internal_bot, assigned_bot in raw_internal_bots:
            internal_bots.append(internal_bot.api_response())
            internal_bot_settings[internal_bot.bot_type.value] = assigned_bot.api_response()
        return internal_bots, internal_bot_settings

    def get_api_bot_scope_list(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        scopes = BotScopeHelper.get_list(ProjectBotScope, project_id=project.id)
        return [scope.api_response() for scope in scopes]

    def get_api_bot_schedule_list(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        schedules = BotScheduleHelper.get_all_by_scope(
            ProjectBotSchedule,
            None,
            project,
            as_api=True,
        )

        return schedules

    def get_api_list_with_columns(self, user: User) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        projects, project_ids = self.get_api_list(user)

        column_service = self._get_service(ProjectColumnService)
        columns = column_service.get_api_list_by_project(cast(list, project_ids))

        return projects, columns

    def get_api_starred_project_list(self, user: User) -> list[dict[str, str]]:
        if not user or user.is_new():
            return []

        raw_projects = self.repo.project.get_all_starred(user)

        projects = []
        all_roles = self.get_all_roles(user)
        roles_dict = {}

        if not user.is_admin:
            for role in all_roles:
                if role.project_id in roles_dict:
                    continue
                roles_dict[role.project_id] = role.actions

        for project in raw_projects:
            api_project = project.api_response()
            api_project["current_auth_role_actions"] = roles_dict[project.id] if not user.is_admin else [ALL_GRANTED]
            projects.append(api_project)

        return projects

    def get_details(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, is_setting: bool
    ) -> tuple[Project, dict[str, Any]] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        response = project.api_response()
        owner = InfraHelper.get_by_id_like(User, project.owner_id, with_deleted=True)
        if not owner:
            return None

        invitation_service: "ProjectInvitationService" = self._get_service_by_name("project_invitation")
        invited_members = invitation_service.get_api_invited_user_list_by_project(project)
        response["all_members"] = [
            owner.api_response(),
            *(self.get_api_assigned_user_list(project)),
            *invited_members,
        ]
        response["invited_member_uids"] = [invitation["uid"] for invitation in invited_members]
        if isinstance(user_or_bot, User):
            response["current_auth_role_actions"] = self.get_user_role_actions_by_project(user_or_bot, project)
        response["labels"] = self._get_service(ProjectLabelService).get_api_list_by_project(project)
        if is_setting:
            roles = self.repo.role.project.get_list(project_id=project.id)
            response["member_roles"] = {}
            for role in roles:
                if role.user_id and role.user_id != project.owner_id:
                    response["member_roles"][role.user_id.to_short_code()] = role.actions
            response["access_groups"] = self._build_access_groups(project, response["all_members"], roles)

        return project, response

    def _build_access_groups(
        self, project: Project, all_members: list[dict[str, Any]], roles: list[ProjectRole]
    ) -> list[dict[str, Any]]:
        role_map = {role.user_id.to_short_code(): role for role in roles if role.user_id}
        groups = {
            "owner": {
                "uid": f"project-role:{project.get_uid()}:owner",
                "role_key": "owner",
                "name": "Owners",
                "description": "Full project control and governance.",
                "member_uids": [],
            },
            "contributor": {
                "uid": f"project-role:{project.get_uid()}:contributor",
                "role_key": "contributor",
                "name": "Contributors",
                "description": "Can update project content and active work.",
                "member_uids": [],
            },
            "viewer": {
                "uid": f"project-role:{project.get_uid()}:viewer",
                "role_key": "viewer",
                "name": "Viewers",
                "description": "Read-only access to the project workspace.",
                "member_uids": [],
            },
        }
        for member in all_members:
            member_uid = str(member.get("uid") or "").strip()
            if not member_uid:
                continue
            if member_uid == project.owner_id.to_short_code():
                groups["owner"]["member_uids"].append(member_uid)
                continue
            role = role_map.get(member_uid)
            if role and role.is_all_granted():
                groups["owner"]["member_uids"].append(member_uid)
            elif role and any(action != ProjectRoleAction.Read.value for action in role.actions):
                groups["contributor"]["member_uids"].append(member_uid)
            else:
                groups["viewer"]["member_uids"].append(member_uid)

        return [
            {
                **group,
                "member_count": len(group["member_uids"]),
            }
            for group in groups.values()
        ]

    def is_assigned(self, user: User, project: TProjectParam | None) -> tuple[bool, ProjectAssignedUser | None]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False, None

        assignee = self.repo.project_assigned_user.find_by_user_and_project(user, project)
        return bool(assignee), assignee

    def are_users_related(self, user: User, target_user: User, project: TProjectParam | None = None) -> bool:
        return bool(self.repo.project.are_users_related(user, target_user, project))

    def toggle_star(self, user: User, project: TProjectParam) -> bool:
        record = self.repo.project_assigned_user.get_with_project_by_user_and_project(user, project)
        if not record:
            return False
        assigned_user, project = record

        self.repo.project_assigned_user.update_starred(user, project, not assigned_user.starred)

        return True

    def set_last_view(self, user: User, project: Project) -> None:
        self.repo.project_assigned_user.set_last_view(user, project)

    def create(self, user: User, title: str, description: str | None = None, project_type: str = "Other") -> Project:
        project = Project(
            owner_id=user.id,
            title=title,
            description=description,
            project_type=project_type,
        )
        self.repo.project.insert(project)

        self.repo.project_column.get_or_create_archive_if_not_exists(project)

        self.repo.project_label.init_defaults(project)

        assigned_user = ProjectAssignedUser(project_id=project.id, user_id=user.id)
        self.repo.project_assigned_user.insert(assigned_user)

        self.repo.role.project.grant_all(user_id=user.id, project_id=project.id)

        internal_bots = self.repo.internal_bot.get_default_list()

        for internal_bot in internal_bots:
            assigned_internal_bot = ProjectAssignedInternalBot(project_id=project.id, internal_bot_id=internal_bot.id)
            self.repo.project_assigned_internal_bot.insert(assigned_internal_bot)

        ProjectActivityTask.project_created(user, project)

        return project

    def update(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, form: dict
    ) -> dict[str, Any] | Literal[True] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        validators: TMutableValidatorMap = {
            "title": "not_empty",
            "description": "default",
            "project_type": "not_empty",
            "ai_description": "default",
        }

        old_record = self.apply_mutates(project, form, validators)
        if not old_record:
            return True

        self.repo.project.update(project)

        model: dict[str, Any] = {}
        for key in validators:
            if key not in form or key not in old_record:
                continue
            model[key] = convert_python_data(getattr(project, key))

        ProjectPublisher.updated(project, model)
        ProjectActivityTask.project_updated(user_or_bot, old_record, project)
        ProjectBotTask.project_updated(user_or_bot, project)

        return model

    def update_assigned_users(self, user: User, project: TProjectParam | None, emails: list[str]) -> bool:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False

        old_assigned_users = self.repo.project_assigned_user.get_all_by_project(project)

        invitation_service: "ProjectInvitationService" = self._get_service_by_name("project_invitation")
        invitation_related_data = invitation_service.get_invitation_related_data(project, emails)

        self.repo.project_assigned_user.delete_all_by_project_and_users(
            project, list(invitation_related_data.user_ids_should_delete)
        )

        result = invitation_service.invite_emails(user, project, invitation_related_data)

        new_assigned_users = self.repo.project_assigned_user.get_all_by_project(project)
        model = {
            "assigned_members": [user.api_response() for user, _ in new_assigned_users],
            "invited_members": invitation_service.get_api_invited_user_list_by_project(project),
        }

        ProjectPublisher.assigned_users_updated(project, model)
        ProjectActivityTask.project_assigned_users_updated(
            user,
            project,
            [user.id for user, _ in old_assigned_users],
            [user.id for user, _ in new_assigned_users],
        )

        return result

    def unassign_assignee(self, user: User, project: TProjectParam | None, target: TUserParam | None) -> bool:
        project = InfraHelper.get_by_id_like(Project, project)
        target_user = InfraHelper.get_by_id_like(User, target)
        if not target_user:
            return False

        if not project or not (self.is_assigned(target_user, project))[0] or project.owner_id == target_user.id:
            return False

        users = self.repo.project_assigned_user.get_all_by_project(project)
        invitations = self.repo.project_invitation.get_all_by_project_with_user(project)
        new_user_emails = [
            *[user.email for user, _ in users if user.id != target_user.id],
            *[invitation.email for invitation, user in invitations if not user or user.id != target_user.id],
        ]

        return self.update_assigned_users(user, project, new_user_emails)

    def update_user_roles(
        self,
        project: TProjectParam | None,
        target_user: TUserParam | None,
        roles: list[ProjectRoleAction],
    ):
        project = InfraHelper.get_by_id_like(Project, project)
        target_user = InfraHelper.get_by_id_like(User, target_user)
        if not project or not target_user or not (self.is_assigned(target_user, project))[0]:
            return False

        if project.owner_id == target_user.id:
            return True

        if ProjectRoleAction.Read not in roles:
            roles.append(ProjectRoleAction.Read)

        role_strs = [role.value for role in roles]
        if roles == list(ProjectRoleAction._member_map_.values()):
            self.repo.role.project.grant_all(user_id=target_user.id, project_id=project.id)
        elif not roles:
            self.repo.role.project.grant_default(user_id=target_user.id, project_id=project.id)
        else:
            self.repo.role.project.grant(actions=role_strs, user_id=target_user.id, project_id=project.id)

        ProjectPublisher.user_roles_updated(project, target_user, role_strs)

        return True

    def change_internal_bot(self, project: TProjectParam | None, internal_bot: TInternalBotParam | None):
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False

        internal_bot = InfraHelper.get_by_id_like(InternalBot, internal_bot)
        if not internal_bot:
            return False

        result = self.repo.project_assigned_internal_bot.find_with_internal_bot_by_project_and_type(
            project, internal_bot.bot_type
        )
        if not result:
            return False
        old_internal_bot, _ = result

        if old_internal_bot.id == internal_bot.id:
            return True

        self.repo.project_assigned_internal_bot.replace_by_project(project, old_internal_bot, internal_bot)

        ProjectPublisher.internal_bot_changed(project, internal_bot.id)

        return True

    def change_internal_bot_settings(
        self,
        project: TProjectParam | None,
        bot_type: InternalBotType,
        use_default_prompt: bool | None = None,
        prompt: str | None = None,
    ):
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False

        result = self.repo.project_assigned_internal_bot.find_with_internal_bot_by_project_and_type(project, bot_type)
        if not result:
            return False
        _, assigned_internal_bot = result

        should_update = False
        if use_default_prompt is not None and assigned_internal_bot.use_default_prompt != use_default_prompt:
            assigned_internal_bot.use_default_prompt = use_default_prompt
            should_update = True

        if prompt is not None and assigned_internal_bot.prompt != prompt:
            assigned_internal_bot.prompt = prompt
            should_update = True

        if not should_update:
            return True

        self.repo.project_assigned_internal_bot.update(assigned_internal_bot)

        ProjectPublisher.internal_bot_settings_changed(project, bot_type, assigned_internal_bot)

        return True

    def delete(self, user: User, project: TProjectParam | None) -> bool:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return False

        started_checkitems = self.repo.checkitem.get_all_started_checkitem_by_project(project)

        checkitem_service = self._get_service(CheckitemService)
        current_time = SafeDateTime.now()
        for checkitem, card in started_checkitems:
            checkitem_service.change_status(
                user,
                project,
                card,
                checkitem,
                CheckitemStatus.Stopped,
                current_time,
                should_publish=False,
            )

        self.repo.project.delete(project)

        ProjectPublisher.deleted(project)
        ProjectActivityTask.project_deleted(user, project)
        ProjectBotTask.project_deleted(user, project)

        return True
