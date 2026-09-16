from typing import cast
from sqlalchemy import exists, func
from sqlalchemy.orm import aliased
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TProjectParam, TUserParam
from ....domain.models import Card, CardAssignedUser, Project, ProjectActivity, ProjectAssignedUser
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

    def get_all_by_user(self, user: TUserParam) -> list[tuple[Project, ProjectAssignedUser, SafeDateTime | None, bool]]:
        user_id = InfraHelper.convert_id(user)
        last_activity_at = self._last_activity_at()
        related_to_current_user = self._related_to_user(user_id)
        query = (
            SqlBuilder.select.tables(Project, ProjectAssignedUser)
            .add_columns(last_activity_at, related_to_current_user)
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

        projects = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            projects = result.all()
        return projects

    def get_all_starred(self, user: TUserParam) -> list[tuple[Project, ProjectAssignedUser, SafeDateTime | None, bool]]:
        user_id = InfraHelper.convert_id(user)
        last_activity_at = self._last_activity_at()
        related_to_current_user = self._related_to_user(user_id)
        projects = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(Project, ProjectAssignedUser)
                .add_columns(last_activity_at, related_to_current_user)
                .join(
                    ProjectAssignedUser,
                    ProjectAssignedUser.column("project_id") == Project.column("id"),
                )
                .where(ProjectAssignedUser.column("user_id") == user_id)
                .where(ProjectAssignedUser.column("starred") == True)  # noqa
                .order_by(
                    func.coalesce(last_activity_at, Project.column("created_at")).desc(),
                    Project.column("id").desc(),
                )
            )
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

    @staticmethod
    def _related_to_user(user_id: SnowflakeID):
        return (
            exists()
            .where(Card.column("project_id") == Project.column("id"))
            .where(Card.column("archived_at").is_(None))
            .where(CardAssignedUser.column("card_id") == Card.column("id"))
            .where(CardAssignedUser.column("user_id") == user_id)
            .correlate(Project)
            .label("related_to_current_user")
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
