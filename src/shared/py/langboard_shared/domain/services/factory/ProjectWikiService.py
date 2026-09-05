from typing import Any, Literal
from ....core.db import EditorContentModel
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.exceptions.WikiContentConflict import WikiContentConflict
from ....core.storage import FileModel
from ....core.types.ParamTypes import TProjectParam, TUserOrBot, TWikiParam
from ....core.utils.Converter import convert_python_data
from ....helpers import InfraHelper
from ....publishers import ProjectWikiPublisher
from ....tasks.activities import ProjectWikiActivityTask
from ....tasks.bots import ProjectWikiBotTask
from ...models import Bot, Project, ProjectWiki, ProjectWikiAssignedUser, ProjectWikiAttachment, User
from .GraphApprovalRequestService import GraphApprovalRequestService
from .NotificationService import NotificationService


class ProjectWikiService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project_wiki"

    def get_by_id_like(self, wiki: TWikiParam | None) -> ProjectWiki | None:
        wiki = InfraHelper.get_by_id_like(ProjectWiki, wiki)
        return wiki

    def get_api_list(self, user_or_bot: TUserOrBot, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        raw_wikis = self.repo.project_wiki.get_all_by_project(project)
        wikis = [self.convert_to_api_response(user_or_bot, project, raw_wiki) for raw_wiki in raw_wikis]

        return wikis

    def convert_to_api_response(self, user_or_bot: TUserOrBot, project: Project, wiki: ProjectWiki) -> dict[str, Any]:
        api_wiki = wiki.api_response()
        api_wiki["assigned_members"] = []
        if wiki.is_public:
            return api_wiki

        assigned_users = self.repo.project_wiki_assigned_user.get_all_by_wiki(wiki)
        assigned_user_ids = [assigned_user.id for assigned_user, _ in assigned_users]

        is_showable = (
            wiki.is_public
            or (
                isinstance(user_or_bot, User)
                and (user_or_bot.is_admin or project.owner_id == user_or_bot.id or user_or_bot.id in assigned_user_ids)
            )
            or isinstance(user_or_bot, Bot)
        )

        if is_showable:
            api_wiki["assigned_members"] = [assigned_user.api_response() for assigned_user, _ in assigned_users]
        else:
            api_wiki = wiki.convert_to_private_api_response()

        return api_wiki

    def get_api_assigned_user_list(self, wiki: TWikiParam | None) -> list[dict[str, Any]]:
        wiki = InfraHelper.get_by_id_like(ProjectWiki, wiki)
        if not wiki:
            return []
        raw_users = self.repo.project_wiki_assigned_user.get_all_by_wiki(wiki)

        users = [user.api_response() for user, _ in raw_users]
        return users

    def is_assigned(self, user: User, wiki: TWikiParam | None) -> bool:
        if user.is_admin:
            return True

        wiki = InfraHelper.get_by_id_like(ProjectWiki, wiki)
        if not wiki:
            return False

        if wiki.is_public:
            return True

        record = self.repo.project_wiki_assigned_user.find_by_user_and_wiki(user, wiki)
        return bool(record)

    def create(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        title: str,
        content: EditorContentModel | None = None,
    ) -> tuple[ProjectWiki, dict[str, Any]] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        max_order = InfraHelper.get_next_order(ProjectWiki, "project_id", project.id)

        wiki = ProjectWiki(
            project_id=project.id,
            title=title,
            content=content or EditorContentModel(),
            order=self.repo.project_wiki.get_next_order(max_order),
        )
        self.repo.project_wiki.insert(wiki)

        api_wiki = wiki.api_response()
        api_wiki["assigned_members"] = []
        ProjectWikiPublisher.created(project, wiki)
        ProjectWikiActivityTask.project_wiki_created(user_or_bot, project, wiki)
        ProjectWikiBotTask.project_wiki_created(user_or_bot, project, wiki)

        return wiki, api_wiki

    def update(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        wiki: TWikiParam | None,
        form: dict,
        *,
        expected_content: str | None = None,
    ) -> dict[str, Any] | Literal[True] | None:
        if expected_content is not None and set(form) != {"content"}:
            raise ValueError("Conditional wiki edits may change only content")
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params

        validators: TMutableValidatorMap = {"title": "not_empty", "content": "default"}

        old_record = self.apply_mutates(wiki, form, validators)
        if not old_record:
            return True

        if expected_content is None:
            self.repo.project_wiki.update(wiki)
        elif not self.repo.project_wiki.update_content_if_current(wiki, expected_content):
            raise WikiContentConflict("Wiki changed after review; no append saved")

        model: dict[str, Any] = {}
        for key in form:
            if key not in validators or key not in old_record:
                continue
            model[key] = convert_python_data(getattr(wiki, key))

        ProjectWikiPublisher.updated(project, wiki, model)

        notification_service = self._get_service(NotificationService)
        if "content" in model:
            notification_service.notify_mentioned_in_wiki(user_or_bot, project, wiki)

        ProjectWikiActivityTask.project_wiki_updated(user_or_bot, project, old_record, wiki)
        ProjectWikiBotTask.project_wiki_updated(user_or_bot, project, wiki)

        return model

    def change_public(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, wiki: TWikiParam | None, is_public: bool
    ) -> tuple[ProjectWiki, Project] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params

        if is_public:
            self.repo.project_wiki_assigned_user.delete_all_by_wiki(wiki)
        else:
            if isinstance(user_or_bot, Bot):
                return None

            project_assigned = self.repo.project_assigned_user.find_by_user_and_project(user_or_bot, project)
            if not project_assigned:
                return None

            model_params: dict[str, Any] = {
                "project_assigned_id": project_assigned.id,
                "project_wiki_id": wiki.id,
            }
            model_params["user_id"] = user_or_bot.id
            assigned_user = ProjectWikiAssignedUser(**model_params)
            self.repo.project_wiki_assigned_user.insert(assigned_user)

        was_public = wiki.is_public
        wiki.is_public = is_public

        self.repo.project_wiki.update(wiki)

        ProjectWikiPublisher.publicity_changed(user_or_bot, project, wiki)
        ProjectWikiActivityTask.project_wiki_publicity_changed(user_or_bot, project, was_public, wiki)
        ProjectWikiBotTask.project_wiki_publicity_changed(user_or_bot, project, wiki)

        return wiki, project

    def update_assignees(
        self, user: User, project: TProjectParam | None, wiki: TWikiParam | None, assign_user_uids: list[str]
    ) -> tuple[ProjectWiki, Project] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params
        if wiki.is_public:
            return None

        old_assigned_users = self.repo.project_wiki_assigned_user.get_all_by_wiki(wiki)

        self.repo.project_wiki_assigned_user.delete_all_by_wiki(wiki)

        target_users: list[User] = []
        if assign_user_uids:
            project_members = self.repo.project_assigned_user.get_all_by_project(
                project, where_users_in=assign_user_uids
            )

            for target_user, project_assigned_user in project_members:
                assigned_user = ProjectWikiAssignedUser(
                    project_assigned_id=project_assigned_user.id, project_wiki_id=wiki.id, user_id=target_user.id
                )
                self.repo.project_wiki_assigned_user.insert(assigned_user)
                target_users.append(target_user)

        ProjectWikiPublisher.assignees_updated(project, wiki, target_users)
        ProjectWikiActivityTask.project_wiki_assignees_updated(
            user,
            project,
            wiki,
            [target_user.id for target_user, _ in old_assigned_users],
            [target_user.id for target_user in target_users],
        )

        return wiki, project

    def change_order(
        self, project: TProjectParam | None, wiki: TWikiParam | None, order: int
    ) -> tuple[Project, ProjectWiki] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params

        old_order = wiki.order
        wiki.order = order
        self.repo.project_wiki.update_column_order(wiki, project, old_order, order)

        ProjectWikiPublisher.order_changed(project, wiki)

        return project, wiki

    def upload_attachment(
        self, user: User, project: TProjectParam | None, wiki: TWikiParam | None, attachment: FileModel
    ) -> ProjectWikiAttachment | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params

        wiki_attachment = ProjectWikiAttachment(
            user_id=user.id,
            project_wiki_id=wiki.id,
            filename=attachment.original_filename,
            file=attachment,
            order=self.repo.project_wiki_attachment.get_next_order(wiki),
        )

        self.repo.project_wiki_attachment.insert(wiki_attachment)

        return wiki_attachment

    def delete(self, user_or_bot: TUserOrBot, project: TProjectParam | None, wiki: TWikiParam | None) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return False
        project, wiki = params

        self._get_service(GraphApprovalRequestService).cancel_pending_by_scope(
            project, ProjectWiki.__tablename__, wiki.get_uid(), reason="project wiki deleted"
        )
        self.repo.project_wiki.delete(wiki)

        ProjectWikiPublisher.deleted(project, wiki)
        ProjectWikiActivityTask.project_wiki_deleted(user_or_bot, project, wiki)
        ProjectWikiBotTask.project_wiki_deleted(user_or_bot, project, wiki)

        return True
