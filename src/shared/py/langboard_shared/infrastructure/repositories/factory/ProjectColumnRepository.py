from sqlalchemy import func
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.types.ParamTypes import TColumnParam, TProjectParam
from ....domain.models import Card, Project, ProjectColumn, ProjectColumnBotSchedule, ProjectColumnBotScope
from ....helpers import InfraHelper


class ProjectColumnRepository(BaseOrderRepository[ProjectColumn, Project]):
    @staticmethod
    def parent_model_cls():
        return Project

    @staticmethod
    def model_cls():
        return ProjectColumn

    @staticmethod
    def name() -> str:
        return "project_column"

    def get_by_id_like(self, column: TColumnParam | None) -> ProjectColumn | None:
        return InfraHelper.get_by_id_like(ProjectColumn, column)

    def get_all_by_project(self, projects: TProjectParam | list[TProjectParam]) -> list[tuple[ProjectColumn, int]]:
        if not isinstance(projects, list):
            projects = [projects]
        project_ids = [InfraHelper.convert_id(project) for project in projects]
        query = SqlBuilder.select.tables(ProjectColumn, func.count(Card.column("id")).label("count")).outerjoin(  # type: ignore
            Card,
            (Card.column("project_column_id") == ProjectColumn.column("id")) & (Card.column("deleted_at") == None),  # noqa
        )

        query = (
            query.where(ProjectColumn.column("project_id").in_(project_ids))
            .order_by(ProjectColumn.column("order").asc())
            .group_by(ProjectColumn.column("id"), ProjectColumn.column("order"))
        )

        raw_columns = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            raw_columns = result.all()

        has_archive_column = {}
        for raw_column in raw_columns:
            column, _ = raw_column
            if column.is_archive:
                has_archive_column[column.project_id] = True

        for project_id in project_ids:
            if project_id in has_archive_column and has_archive_column[project_id]:
                continue
            archive_column = self.get_or_create_archive_if_not_exists(project_id)
            raw_columns.append((archive_column, 0))

        return raw_columns

    def get_or_create_archive_if_not_exists(self, project: TProjectParam) -> ProjectColumn:
        project_id = InfraHelper.convert_id(project)
        archive_column = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectColumn)
                .where(
                    (ProjectColumn.column("project_id") == project_id) & ProjectColumn.column("is_archive") == True  # noqa
                )
                .limit(1)
            )
            archive_column = result.first()
        if archive_column:
            return archive_column

        max_order = self.get_next_order(project_id)

        column = ProjectColumn(
            project_id=project_id,
            name=ProjectColumn.DEFAULT_ARCHIVE_COLUMN_NAME,
            order=max_order,
            is_archive=True,
        )

        with DbSession.use(readonly=False) as db:
            db.insert(column)

        return column

    def get_bot_scopes_by_project(self, project: TProjectParam) -> list[ProjectColumnBotScope]:
        project_id = InfraHelper.convert_id(project)

        scopes = BotScopeHelper.get_list(
            ProjectColumnBotScope,
            lambda q: q.join(
                ProjectColumn,
                ProjectColumn.column("id") == ProjectColumnBotScope.column("project_column_id"),
            ).where(ProjectColumn.column("project_id") == project_id),
        )

        return scopes

    def get_bot_schedules_by_project(self, project: TProjectParam, columns: list[TColumnParam] | None):
        project_id = InfraHelper.convert_id(project)
        scope_column_ids: list[int] = []
        if isinstance(columns, list):
            scope_column_ids = [InfraHelper.convert_id(column) for column in columns]
        else:
            with DbSession.use(readonly=True) as db:
                result = db.exec(
                    SqlBuilder.select.column(ProjectColumn.id).where(ProjectColumn.column("project_id") == project_id)  # type: ignore
                )
                scope_column_ids = list(result.all())

        if not scope_column_ids:
            return []

        schedules = BotScheduleHelper.get_all_by_scope(
            ProjectColumnBotSchedule,
            None,
            (ProjectColumn, scope_column_ids),
            as_api=False,
        )

        return schedules

    def count_cards(self, project: TProjectParam, column: TColumnParam) -> int:
        project_id = InfraHelper.convert_id(project)
        column_id = InfraHelper.convert_id(column)
        sql_query = SqlBuilder.select.count(Card, Card.id).where(  # type: ignore
            (Card.column("project_id") == project_id) & (Card.column("project_column_id") == column_id)
        )
        count = 0
        with DbSession.use(readonly=True) as db:
            result = db.exec(sql_query)
            count = result.first() or 0
        return count

    def reorder_after_deleted(self, project: TProjectParam, deleted_order: int) -> None:
        project_id = InfraHelper.convert_id(project)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(ProjectColumn)
                .values({ProjectColumn.order: ProjectColumn.order - 1})
                .where(
                    (ProjectColumn.column("project_id") == project_id) & (ProjectColumn.column("order") > deleted_order)
                )
            )
