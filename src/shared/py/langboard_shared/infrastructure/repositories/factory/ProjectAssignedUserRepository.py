from typing import Sequence
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TProjectParam, TUserParam
from ....domain.models import Project, ProjectAssignedUser, ProjectRole, User
from ....helpers import InfraHelper


class ProjectAssignedUserRepository(BaseRepository[ProjectAssignedUser]):
    @staticmethod
    def model_cls():
        return ProjectAssignedUser

    @staticmethod
    def name() -> str:
        return "project_assigned_user"

    def get_all_by_project(
        self, project: TProjectParam, where_users_in: Sequence[TUserParam] | None = None
    ) -> list[tuple[User, ProjectAssignedUser]]:
        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.tables(User, ProjectAssignedUser)
            .join(
                ProjectAssignedUser,
                User.column("id") == ProjectAssignedUser.column("user_id"),
            )
            .where(ProjectAssignedUser.column("project_id") == project_id)
        )

        if where_users_in is not None:
            if not isinstance(where_users_in, Sequence) or isinstance(where_users_in, str):
                where_users_in = [where_users_in]
            user_ids = [InfraHelper.convert_id(user) for user in where_users_in]
            query = query.where(User.column("id").in_(user_ids))

        users = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            users = result.all()
        return users

    def get_by_user_and_project(self, user: TUserParam, project: TProjectParam) -> ProjectAssignedUser | None:
        user_id = InfraHelper.convert_id(user)
        project_id = InfraHelper.convert_id(project)

        assigned_user = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser).where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
            )
            assigned_user = result.first()
        return assigned_user

    def get_with_project_by_user_and_project(
        self, user: TUserParam, project: TProjectParam
    ) -> tuple[ProjectAssignedUser, Project] | None:
        project_id = InfraHelper.convert_id(project)
        user_id = InfraHelper.convert_id(user)

        record = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(ProjectAssignedUser, Project)
                .join(
                    ProjectAssignedUser,
                    Project.column("id") == ProjectAssignedUser.column("project_id"),
                )
                .where((Project.column("id") == project_id) & (ProjectAssignedUser.column("user_id") == user_id))
                .limit(1)
            )
            record = result.first()
        return record

    def find_by_user_and_project(self, user: TUserParam, project: TProjectParam) -> ProjectAssignedUser | None:
        user_id = InfraHelper.convert_id(user)
        project_id = InfraHelper.convert_id(project)

        assignee = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser)
                .where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
                .limit(1)
            )
            assignee = result.first()
        return assignee

    def update_starred(self, user: TUserParam, project: TProjectParam, starred: bool) -> None:
        user_id = InfraHelper.convert_id(user)
        project_id = InfraHelper.convert_id(project)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(ProjectAssignedUser)
                .values(starred=starred)
                .where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
            )

    def set_last_view(self, user: TUserParam, project: TProjectParam) -> None:
        user_id = InfraHelper.convert_id(user)
        project_id = InfraHelper.convert_id(project)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(ProjectAssignedUser)
                .values(last_viewed_at=SafeDateTime.now())
                .where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
            )

    def delete_all_by_project_and_users(self, project: TProjectParam, users: Sequence[TUserParam]):
        if not isinstance(users, Sequence) or isinstance(users, str):
            users = [users]

        project_id = InfraHelper.convert_id(project)
        user_ids = [InfraHelper.convert_id(user) for user in users]

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ProjectRole).where(
                    (ProjectRole.column("project_id") == project_id) & (ProjectRole.column("user_id").in_(user_ids))
                )
            )

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ProjectAssignedUser).where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id").in_(user_ids))
                )
            )
