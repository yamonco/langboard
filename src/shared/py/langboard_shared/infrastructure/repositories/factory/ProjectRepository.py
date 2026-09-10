from typing import cast
from sqlalchemy import func
from sqlalchemy.orm import aliased
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TProjectParam, TUserParam
from ....domain.models import Project, ProjectActivity, ProjectAssignedUser
from ....helpers import InfraHelper


class ProjectRepository(BaseRepository[Project]):
    @staticmethod
    def model_cls():
        return Project

    @staticmethod
    def name() -> str:
        return "project"

    def get_by_id_like(self, project: TProjectParam | None) -> Project | None:
        return InfraHelper.get_by_id_like(Project, project)

    def get_all_by_user(
        self, user: TUserParam, limit: int | None = None
    ) -> list[tuple[Project, ProjectAssignedUser, SafeDateTime | None]]:
        user_id = InfraHelper.convert_id(user)
        last_activity_at = self._last_activity_at()
        query = (
            SqlBuilder.select.tables(Project, ProjectAssignedUser)
            .add_columns(last_activity_at)
            .join(
                ProjectAssignedUser,
                Project.column("id") == ProjectAssignedUser.column("project_id"),
            )
            .where(ProjectAssignedUser.column("user_id") == user_id)
            .order_by(
                ProjectAssignedUser.column("starred").desc(),
                func.coalesce(last_activity_at, Project.column("created_at")).desc(),
                Project.column("id").desc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)

        projects = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            projects = result.all()
        return projects

    def get_all_starred(
        self, user: TUserParam, limit: int | None = None
    ) -> list[tuple[Project, ProjectAssignedUser, SafeDateTime | None]]:
        user_id = InfraHelper.convert_id(user)
        last_activity_at = self._last_activity_at()
        query = (
            SqlBuilder.select.tables(Project, ProjectAssignedUser)
            .add_columns(last_activity_at)
            .join(
                ProjectAssignedUser,
                ProjectAssignedUser.column("project_id") == Project.column("id"),
            )
            .where(ProjectAssignedUser.column("user_id") == user_id)
            .where(ProjectAssignedUser.column("starred") == True)  # noqa: E712
            .order_by(
                func.coalesce(last_activity_at, Project.column("created_at")).desc(),
                Project.column("id").desc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)

        projects = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            projects = result.all()
        return projects

    @staticmethod
    def _last_activity_at():
        return (
            SqlBuilder.select.column(func.max(ProjectActivity.column("created_at")))
            .where(ProjectActivity.column("project_id") == Project.column("id"))
            .correlate(Project)
            .scalar_subquery()
            .label("last_activity_at")
        )

    def are_users_related(
        self, user: TUserParam, target_user: TUserParam, project: TProjectParam | None = None
    ) -> bool:
        user_id = InfraHelper.convert_id(user)
        target_user_id = InfraHelper.convert_id(target_user)

        user_a = aliased(ProjectAssignedUser)
        user_b = aliased(ProjectAssignedUser)

        query = (
            SqlBuilder.select.column(user_a.id)  # type: ignore
            .join(
                user_b,
                cast(InstrumentedAttribute, user_a.project_id) == user_b.project_id,
            )
            .where((user_a.user_id == user_id) & (user_b.user_id == target_user_id))
            .limit(1)
        )

        if project:
            project = InfraHelper.convert_id(project)
            query = query.where((user_a.project_id == project) & (user_b.project_id == project))

        record = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            record = result.first()
        return bool(record)
