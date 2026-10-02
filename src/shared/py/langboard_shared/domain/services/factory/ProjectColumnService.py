import logging
from collections.abc import Sequence
from typing import Any
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.db import SqlBuilder
from ....core.domain import BaseDomainService
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TColumnParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import ProjectColumnPublisher
from ....tasks.activities import ProjectColumnActivityTask
from ....tasks.bots import ProjectColumnBotTask
from ....tasks.webhooks.ExecutionReadinessUow import execution_readiness_uow
from ...models import Project, ProjectColumn, ProjectColumnBotSchedule, ProjectColumnBotScope
from .GraphApprovalRequestService import GraphApprovalRequestService


class ProjectColumnService(BaseDomainService):
    def _validate_workflow_stage(self, key: str | None) -> None:
        if key is None:
            return
        definition = self.repo.workflow_stage.get_by_keys({key}).get(key)
        if definition is None or not definition.is_active:
            raise ValueError("Unknown or inactive workflow stage")

    def get_workflow_stage_options(self, project: TProjectParam) -> list[dict]:
        columns = InfraHelper.get_all_by(ProjectColumn, "project_id", InfraHelper.convert_id(project))
        bound_keys = {column.workflow_stage for column in columns if not column.is_archive and column.workflow_stage}
        from ...models import WorkflowStageDefinition

        return [
            stage.api_response()
            for stage in sorted(
                InfraHelper.get_all(WorkflowStageDefinition), key=lambda stage: (stage.order, stage.key)
            )
            if stage.is_active or stage.key in bound_keys
        ]

    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project_column"

    def get_by_id_like(self, column: TColumnParam | None) -> ProjectColumn | None:
        column = InfraHelper.get_by_id_like(ProjectColumn, column)
        return column

    def get_api_list_by_project(self, projects: TProjectParam | list[TProjectParam]) -> list[dict[str, Any]]:
        raw_columns = self.repo.project_column.get_all_by_project(projects)
        work_counts = self.repo.project_column.get_work_counts(projects)
        guidance = self.get_workflow_guidance([column for column, _ in raw_columns])

        columns = []
        for raw_column, count in raw_columns:
            if getattr(raw_column, "deleted_at", None) is not None:
                continue
            columns.append(
                {
                    **raw_column.api_response(),
                    **guidance[raw_column.id],
                    "count": count,
                    **work_counts.get(raw_column.id, {"open_count": 0, "incomplete_count": 0}),
                }
            )

        return columns

    def get_workflow_guidance(self, columns: Sequence[ProjectColumn]) -> dict[SnowflakeID, dict[str, Any]]:
        """Resolve canonical registry guidance once per batch, retaining both sources.

        An inactive definition still explains an existing binding. Missing keys
        remain explicit; column display names never imply a stage.
        """
        stages = self.repo.workflow_stage.get_by_keys(
            {column.workflow_stage for column in columns if column.workflow_stage}
        )
        result = {}
        for column in columns:
            stage = stages.get(column.workflow_stage)
            stage_description = stage.description if stage else ""
            column_description = column.description
            parts = []
            if stage_description.strip():
                parts.append(f"Workflow stage:\n{stage_description}")
            if column_description.strip():
                parts.append(f"Column:\n{column_description}")
            result[column.id] = {
                "workflow_stage_description": stage_description,
                "column_description": column_description,
                "workflow_guidance": "\n\n".join(parts),
                "workflow_stage_status": "active"
                if stage and stage.is_active
                else "inactive"
                if stage
                else "missing"
                if column.workflow_stage
                else "unclassified",
            }
        return result

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
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        name: str,
        description: str = "",
        *,
        dispatch_effects: bool = True,
        workflow_stage: str | None = None,
        order_override: int | None = None,
    ) -> ProjectColumn | None:
        """Create a workflow column with optional guidance, preserving legacy name-only callers."""
        if len(description) > 4096:
            raise ValueError("Column description must not exceed 4096 characters")
        self._validate_workflow_stage(workflow_stage)
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        column = ProjectColumn(
            project_id=project.id,
            name=name,
            description=description,
            workflow_stage=workflow_stage,
            order=order_override if order_override is not None else self.repo.project_column.get_next_order(project),
        )

        self.repo.project_column.insert(column)

        if dispatch_effects:
            self.dispatch_created(user_or_bot, project, column)

        return column

    def dispatch_created(
        self, user_or_bot: TUserOrBot, project: Project, column: ProjectColumn, *, include_bot: bool = True
    ) -> None:
        ProjectColumnPublisher.created(project, column)
        ProjectColumnActivityTask.project_column_created(user_or_bot, project, column)
        if include_bot:
            ProjectColumnBotTask.project_column_created(user_or_bot, project, column)

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

    def change_workflow_stage(
        self, project: TProjectParam | None, column: TColumnParam | None, workflow_stage: str | None
    ) -> bool:
        """Store an explicit meaning; never classify from a mutable column name."""
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params
        if column.project_id != project.id:
            return False
        with execution_readiness_uow() as execution:
            column = execution.db.exec(
                SqlBuilder.select.table(ProjectColumn)
                .where(ProjectColumn.column("id") == column.id)
                .where(ProjectColumn.column("project_id") == project.id)
                .with_for_update()
            ).first()
            if column is None or column.is_archive:
                return False
            if column.workflow_stage == workflow_stage:
                return True
            self._validate_workflow_stage(workflow_stage)
            # ponytail: rare workflow edits fence the project; scope to the column
            # and blocks dependents if large-board latency makes this costly.
            execution.watch_project(project.id)
            column.workflow_stage = workflow_stage
            self.repo.project_column.update(column)
            affected_ids = list(execution.before)
        ProjectColumnPublisher.workflow_stage_changed(project, column)
        from .CardService import CardService

        self._get_service(CardService).publish_work_states(project, affected_ids)
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

    def get_dock_snapshot(self, project: TProjectParam) -> dict[str, Any] | None:
        return self.repo.project_column.get_dock_snapshot(project)

    def replace_dock_columns(
        self, project: TProjectParam | None, column_uids: list[str], expected_revision: int
    ) -> dict[str, Any] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None
        result = self.repo.project_column.replace_dock_columns(project, column_uids, expected_revision)
        if result is not None:
            ProjectColumnPublisher.dock_changed(project, result)
        return result

    def delete(self, user_or_bot: TUserOrBot, project: TProjectParam | None, column: TColumnParam | None) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return False
        project, column = params
        if column.is_archive:
            return False

        archive_column = self.repo.project_column.get_or_create_archive_if_not_exists(project)
        count_cards_in_source = self.repo.project_column.count_cards(project, column)
        count_work_cards_in_source = self.repo.project_column.count_cards(project, column, exclude_linked_wikis=True)

        current_time = SafeDateTime.now()

        self.repo.card.move_all_by_column(column, archive_column, count_cards_in_source, is_archive=True)

        BotScopeHelper.delete_by_scope(ProjectColumnBotScope, column)
        BotScheduleHelper.unschedule_by_scope(ProjectColumnBotSchedule, column)
        self._get_service(GraphApprovalRequestService).cancel_pending_by_scope(
            project,
            ProjectColumn.__tablename__,
            column.get_uid(),
            reason="project column deleted",
        )

        dock_snapshot = self.repo.project_column.delete_with_dock_snapshot(project, column)
        if dock_snapshot is None:
            return False

        ProjectColumnPublisher.deleted(
            project, column, archive_column, current_time, count_cards_in_source, count_work_cards_in_source
        )
        ProjectColumnPublisher.dock_changed(project, dock_snapshot)
        ProjectColumnActivityTask.project_column_deleted(user_or_bot, project, column)
        ProjectColumnBotTask.project_column_deleted(user_or_bot, project, column)

        return True
