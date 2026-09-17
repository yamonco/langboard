from typing import Any
from sqlalchemy import case, func, select
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.types.ParamTypes import TColumnParam, TProjectParam
from ....domain.models import Card, Project, ProjectColumn, ProjectColumnBotSchedule, ProjectColumnBotScope
from ....domain.models.ProjectColumn import ProjectColumnDockConflict
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

    def get_dock_snapshot(self, project: TProjectParam) -> dict[str, Any] | None:
        # One primary-database statement keeps the revision and ordered slots coherent.
        query = (
            select(Project, ProjectColumn)
            .outerjoin(
                ProjectColumn,
                (ProjectColumn.project_id == Project.id)
                & ProjectColumn.deleted_at.is_(None)
                & (ProjectColumn.is_archive == False)  # noqa: E712
                & ProjectColumn.dock_order.is_not(None),
            )
            .where((Project.id == InfraHelper.convert_id(project)) & Project.deleted_at.is_(None))
            .order_by(ProjectColumn.dock_order.asc(), ProjectColumn.id.asc())
        )
        with DbSession.use(readonly=False) as db:
            rows = db.exec(query).all()
        if not rows:
            return None
        return {
            "column_uids": [column.get_uid() for _, column in rows if column is not None],
            "revision": rows[0][0].dock_revision,
        }

    def replace_dock_columns(
        self, project: TProjectParam, column_uids: list[str], expected_revision: int
    ) -> dict[str, Any] | None:
        """Replace shared shortcuts without changing board column positions."""
        if len(column_uids) != len(set(column_uids)):
            return None
        project_id = InfraHelper.convert_id(project)
        conflict = False
        with DbSession.use(readonly=False) as db:
            # Serialize whole-list replacements, including an initially empty dock.
            locked = db.exec(
                SqlBuilder.select.table(Project).where(Project.column("id") == project_id).with_for_update()
            ).first()
            if locked is None:
                return None
            if locked.dock_revision != expected_revision:
                conflict = True
            else:
                columns = db.exec(
                    SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.column("project_id") == project_id)
                ).all()
                eligible = {column.get_uid(): column.id for column in columns if not column.is_archive}
                if any(uid not in eligible for uid in column_uids):
                    return None
                positions = {eligible[uid]: index for index, uid in enumerate(column_uids)}
                if all(column.dock_order == positions.get(column.id) for column in columns):
                    return {"column_uids": column_uids, "revision": locked.dock_revision}
                value = case(positions, value=ProjectColumn.column("id"), else_=None) if positions else None
                db.exec(
                    SqlBuilder.update.table(ProjectColumn)
                    .values(dock_order=value)
                    .where(
                        (ProjectColumn.column("project_id") == project_id)
                        & (ProjectColumn.column("deleted_at").is_(None))
                    )
                )
                revision = locked.dock_revision + 1
                db.exec(
                    SqlBuilder.update.table(Project)
                    .values(dock_revision=revision)
                    .where(Project.column("id") == project_id)
                )
        if conflict:
            # A rejected intent is not a failed database transaction.
            raise ProjectColumnDockConflict()
        return {"column_uids": column_uids, "revision": revision}

    def delete_with_dock_snapshot(self, project: TProjectParam, column: TColumnParam) -> dict[str, Any] | None:
        project_id = InfraHelper.convert_id(project)
        column_id = InfraHelper.convert_id(column)
        with DbSession.use(readonly=False) as db:
            locked = db.exec(
                SqlBuilder.select.table(Project).where(Project.column("id") == project_id).with_for_update()
            ).first()
            if locked is None:
                return None
            columns = db.exec(
                SqlBuilder.select.table(ProjectColumn).where(ProjectColumn.column("project_id") == project_id)
            ).all()
            target = next((item for item in columns if item.id == column_id and not item.is_archive), None)
            if target is None:
                return None
            pinned = sorted(
                (
                    item
                    for item in columns
                    if item.id != target.id and not item.is_archive and item.dock_order is not None
                ),
                key=lambda item: (item.dock_order, item.id),
            )
            db.exec(SqlBuilder.delete.table(ProjectColumn).where(ProjectColumn.column("id") == target.id))
            db.exec(
                SqlBuilder.update.table(ProjectColumn)
                .values({ProjectColumn.order: ProjectColumn.order - 1})
                .where(
                    (ProjectColumn.column("project_id") == project_id) & (ProjectColumn.column("order") > target.order)
                )
            )
            revision = locked.dock_revision
            if target.dock_order is not None:
                positions = {item.id: index for index, item in enumerate(pinned)}
                value = case(positions, value=ProjectColumn.column("id"), else_=None) if positions else None
                db.exec(
                    SqlBuilder.update.table(ProjectColumn)
                    .values(dock_order=value)
                    .where(
                        (ProjectColumn.column("project_id") == project_id)
                        & ProjectColumn.column("deleted_at").is_(None)
                    )
                )
                revision += 1
                db.exec(
                    SqlBuilder.update.table(Project)
                    .values(dock_revision=revision)
                    .where(Project.column("id") == project_id)
                )
        return {"column_uids": [item.get_uid() for item in pinned], "revision": revision}

    def get_all_by_project(
        self,
        projects: TProjectParam | list[TProjectParam],
        limit: int | None = None,
    ) -> list[tuple[ProjectColumn, int]]:
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
