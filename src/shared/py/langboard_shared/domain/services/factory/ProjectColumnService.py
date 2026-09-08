import logging
from typing import Any
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.domain import BaseDomainService
from ....core.types import SafeDateTime, SnowflakeID
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

    def get_api_list_by_project(self, projects: TProjectParam | list[TProjectParam]) -> list[dict[str, Any]]:
        raw_columns = self.repo.project_column.get_all_by_project(projects)

        columns = []
        for raw_column, count in raw_columns:
            columns.append({**raw_column.api_response(), "count": count})

        return columns

    def get_api_bot_scopes_by_project(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        scopes = BotScopeHelper.get_list(
            ProjectColumnBotScope,
            lambda q: q.join(
                ProjectColumn,
                ProjectColumn.column("id") == ProjectColumnBotScope.column("project_column_id"),
            ).where(ProjectColumn.column("project_id") == project.id),
        )
        return [scope.api_response() for scope in scopes]

    def get_api_bot_schedule_list_by_project(
        self, project: TProjectParam | None, columns: list[dict] | list[ProjectColumn] | None
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        scope_column_ids: list[int] = []
        if isinstance(columns, list):
            scope_column_ids = [
                SnowflakeID.from_short_code(column["uid"]) if isinstance(column, dict) else column.id
                for column in columns
            ]
        else:
            scope_column_ids = [column.id for column in InfraHelper.get_all_by(ProjectColumn, "project_id", project.id)]

        if not scope_column_ids:
            return []

        schedules = BotScheduleHelper.get_all_by_scope(
            ProjectColumnBotSchedule,
            None,
            (ProjectColumn, scope_column_ids),
            as_api=True,
        )
        return schedules

    def create(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, name: str, description: str = ""
    ) -> ProjectColumn | None:
        """Create a workflow column with optional guidance, preserving legacy name-only callers."""
        if len(description) > 4096:
            raise ValueError("Column description must not exceed 4096 characters")
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        column = ProjectColumn(
            project_id=project.id,
            name=name,
            description=description,
            order=self.repo.project_column.get_next_order(project),
        )

        self.repo.project_column.insert(column)

        ProjectColumnPublisher.created(project, column)
        ProjectColumnActivityTask.project_column_created(user_or_bot, project, column)
        ProjectColumnBotTask.project_column_created(user_or_bot, project, column)

        return column

    def change_description(self, project: TProjectParam | None, column: TColumnParam | None, description: str) -> bool:
        """Change guidance only within the requested board; never rename or move cards."""
        if len(description) > 4096:
            raise ValueError("Column description must not exceed 4096 characters")
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params
        if column.is_archive:
            return False
        if column.description == description:
            return True
        column.description = description
        self.repo.project_column.update(column)
        ProjectColumnPublisher.description_changed(project, column)
        logging.getLogger(__name__).info("Updated workflow guidance for column %s", column.get_uid())
        return True

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
