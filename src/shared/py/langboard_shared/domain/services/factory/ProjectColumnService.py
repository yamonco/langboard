from typing import Any
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.domain import BaseDomainService
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TColumnParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import ProjectColumnPublisher
from ....tasks.activities import ProjectColumnActivityTask
from ....tasks.bots import ProjectColumnBotTask
from ...models import Project, ProjectColumn, ProjectColumnBotSchedule, ProjectColumnBotScope
from .GraphApprovalRequestService import GraphApprovalRequestService


class ProjectColumnService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project_column"

    def get_by_id_like(self, column: TColumnParam | None) -> ProjectColumn | None:
        column = InfraHelper.get_by_id_like(ProjectColumn, column)
        return column

    def get_api_list_by_project(
        self,
        projects: TProjectParam | list[TProjectParam],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        raw_columns = self.repo.project_column.get_all_by_project(projects, limit=limit)

        columns = []
        for raw_column, count in raw_columns:
            columns.append({**raw_column.api_response(), "count": count})

        return columns

    def get_api_bot_scopes_by_project(
        self, project: TProjectParam | None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        scopes = BotScopeHelper.get_list(
            ProjectColumnBotScope,
            lambda q: q.join(
                ProjectColumn,
                ProjectColumn.column("id") == ProjectColumnBotScope.column("project_column_id"),
            ).where(ProjectColumn.column("project_id") == project.id),
            limit=limit,
        )
        return [scope.api_response() for scope in scopes]

    def get_api_bot_scopes_by_column(
        self,
        column: TColumnParam | None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        column = InfraHelper.get_by_id_like(ProjectColumn, column)
        if not column:
            return []

        scopes = BotScopeHelper.get_list(
            ProjectColumnBotScope,
            limit=limit,
            project_column_id=column.id,
        )
        return [scope.api_response() for scope in scopes]

    def get_api_bot_schedule_list_by_project(
        self,
        project: TProjectParam | None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        pagination = TimeBasedPagination(page=1, limit=limit) if limit is not None else None
        return BotScheduleHelper.get_all_by_project_columns(project, pagination=pagination)

    def create(self, user_or_bot: TUserOrBot, project: TProjectParam | None, name: str) -> ProjectColumn | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        column = ProjectColumn(
            project_id=project.id,
            name=name,
            order=self.repo.project_column.get_next_order(project),
        )

        self.repo.project_column.insert(column)

        ProjectColumnPublisher.created(project, column)
        ProjectColumnActivityTask.project_column_created(user_or_bot, project, column)
        ProjectColumnBotTask.project_column_created(user_or_bot, project, column)

        return column

    def change_name(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, column: TColumnParam | None, name: str
    ) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params

        old_name = column.name
        column.name = name

        self.repo.project_column.update(column)

        ProjectColumnPublisher.name_changed(project, column, name)
        ProjectColumnActivityTask.project_column_name_changed(user_or_bot, project, old_name, column)
        ProjectColumnBotTask.project_column_name_changed(user_or_bot, project, column)

        return True

    def change_order(self, project: TProjectParam | None, column: TColumnParam | None, order: int) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params

        old_order = column.order
        column.order = order
        self.repo.project_column.update_column_order(column, project, old_order, order)

        ProjectColumnPublisher.order_changed(project, column)

        return True

    def delete(self, user_or_bot: TUserOrBot, project: TProjectParam | None, column: TColumnParam | None) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params
        if column.is_archive:
            return False

        archive_column = self.repo.project_column.get_or_create_archive_if_not_exists(project)
        count_cards_in_archive = self.repo.project_column.count_cards(project, archive_column)

        current_time = SafeDateTime.now()

        self.repo.card.move_all_by_column(column, archive_column, count_cards_in_archive, is_archive=True)

        BotScopeHelper.delete_by_scope(ProjectColumnBotScope, column)
        BotScheduleHelper.unschedule_by_scope(ProjectColumnBotSchedule, column)
        self._get_service(GraphApprovalRequestService).cancel_pending_by_scope(
            project,
            ProjectColumn.__tablename__,
            column.get_uid(),
            reason="project column deleted",
        )

        self.repo.project_column.delete(column)

        self.repo.project_column.reorder_after_deleted(project, column.order)

        ProjectColumnPublisher.deleted(project, column, archive_column, current_time, count_cards_in_archive)
        ProjectColumnActivityTask.project_column_deleted(user_or_bot, project, column)
        ProjectColumnBotTask.project_column_deleted(user_or_bot, project, column)

        return True
