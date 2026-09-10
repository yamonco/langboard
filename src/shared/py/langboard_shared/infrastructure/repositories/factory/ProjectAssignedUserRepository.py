from typing import Mapping, Sequence
from sqlalchemy import func
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TProjectParam, TUserParam
from ....domain.models import (
    IdentityProvider,
    Project,
    ProjectAssignedUser,
    ProjectRole,
    ProjectUserRelationship,
    User,
    UserIdentityLink,
)
from ....helpers import InfraHelper


class ProjectAssignedUserRepository(BaseRepository[ProjectAssignedUser]):
    @staticmethod
    def model_cls():
        return ProjectAssignedUser

    @staticmethod
    def name() -> str:
        return "project_assigned_user"

    def get_all_by_project(
        self,
        project: TProjectParam,
        where_users_in: Sequence[TUserParam] | None = None,
        limit: int | None = None,
        *,
        consistent: bool = False,
    ) -> list[tuple[User, ProjectAssignedUser]]:
        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.tables(User, ProjectAssignedUser)
            .join(
                ProjectAssignedUser,
                User.column("id") == ProjectAssignedUser.column("user_id"),
            )
            .where(ProjectAssignedUser.column("project_id") == project_id)
            .order_by(ProjectAssignedUser.column("id").asc())
        )

        if where_users_in is not None:
            if not isinstance(where_users_in, Sequence) or isinstance(where_users_in, str):
                where_users_in = [where_users_in]
            user_ids = [InfraHelper.convert_id(user) for user in where_users_in]
            query = query.where(User.column("id").in_(user_ids))
        if limit is not None:
            query = query.limit(limit)

        users = []
        with DbSession.use(readonly=not consistent) as db:
            result = db.exec(query)
            users = result.all()
        return users

    def count_by_project(self, project: TProjectParam) -> int:
        project_id = InfraHelper.convert_id(project)
        with DbSession.use(readonly=True) as db:
            count = db.exec(
                SqlBuilder.select.column(func.count(ProjectAssignedUser.column("id"))).where(
                    ProjectAssignedUser.column("project_id") == project_id
                )
            ).first()
        return int(count or 0)

    def get_by_user_and_project(self, user: TUserParam, project: TProjectParam) -> ProjectAssignedUser | None:
        user_id = InfraHelper.convert_id(user)
        project_id = InfraHelper.convert_id(project)

        assigned_user = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser)
                .where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
                .limit(1)
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

    def ensure_assigned(self, project: TProjectParam, user: TUserParam) -> tuple[ProjectAssignedUser, bool]:
        project_id = InfraHelper.convert_id(project)
        user_id = InfraHelper.convert_id(user)
        assigned_user = ProjectAssignedUser(project_id=project_id, user_id=user_id)
        with DbSession.use(readonly=False) as db:
            locked_project = db.exec(
                SqlBuilder.select.column(Project.column("id"))
                .where(Project.column("id") == project_id)
                .limit(1)
                .with_for_update()
            ).first()
            if locked_project is None:
                raise ValueError("Project not found")

            existing = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser)
                .where(
                    (ProjectAssignedUser.column("project_id") == project_id)
                    & (ProjectAssignedUser.column("user_id") == user_id)
                )
                .limit(1)
            ).first()
            if existing is not None:
                return existing, False

            db.insert(assigned_user)
        return assigned_user, True

    def reconcile_scim_project_roles(
        self,
        project: TProjectParam,
        issuer: str,
        desired: Mapping[SnowflakeID, tuple[User, list[str]]],
    ) -> None:
        """Apply and verify one SCIM-managed project entitlement snapshot atomically."""

        project_id = InfraHelper.convert_id(project)
        normalized_issuer = issuer.rstrip("/")
        if not normalized_issuer:
            raise ValueError("SCIM issuer is required")

        with DbSession.use(readonly=False) as db:
            locked_project = db.exec(
                SqlBuilder.select.columns(Project.column("id"), Project.column("owner_id"))
                .where(Project.column("id") == project_id)
                .with_for_update()
            ).first()
            if locked_project is None:
                raise ValueError("Project not found")
            _, owner_id = locked_project

            assigned_user_ids = set(
                db.exec(
                    SqlBuilder.select.column(ProjectAssignedUser.column("user_id")).where(
                        ProjectAssignedUser.column("project_id") == project_id
                    )
                ).all()
            )
            managed_user_ids = set(
                db.exec(
                    SqlBuilder.select.column(ProjectAssignedUser.column("user_id"))
                    .join(
                        UserIdentityLink,
                        ProjectAssignedUser.column("user_id") == UserIdentityLink.column("user_id"),
                    )
                    .where(ProjectAssignedUser.column("project_id") == project_id)
                    .where(UserIdentityLink.column("provider") == IdentityProvider.Scim)
                    .where(UserIdentityLink.column("issuer") == normalized_issuer)
                ).all()
            )

            desired_actions = {user_id: actions for user_id, (_, actions) in desired.items() if user_id != owner_id}
            for user_id, actions in desired_actions.items():
                if user_id not in assigned_user_ids:
                    db.insert(ProjectAssignedUser(project_id=project_id, user_id=user_id))
                    assigned_user_ids.add(user_id)

                role = db.exec(
                    SqlBuilder.select.table(ProjectRole)
                    .where(ProjectRole.column("project_id") == project_id)
                    .where(ProjectRole.column("user_id") == user_id)
                    .limit(1)
                ).first()
                if role is None:
                    db.insert(ProjectRole(project_id=project_id, user_id=user_id, actions=actions))
                elif set(role.actions) != set(actions):
                    role.actions = actions
                    db.update(role)

            stale_user_ids = managed_user_ids - set(desired_actions) - {owner_id}
            if stale_user_ids:
                db.exec(
                    SqlBuilder.delete.table(ProjectRole)
                    .where(ProjectRole.column("project_id") == project_id)
                    .where(ProjectRole.column("user_id").in_(stale_user_ids))
                )
                db.exec(
                    SqlBuilder.delete.table(ProjectAssignedUser)
                    .where(ProjectAssignedUser.column("project_id") == project_id)
                    .where(ProjectAssignedUser.column("user_id").in_(stale_user_ids))
                )
                assigned_user_ids -= stale_user_ids

            self._repair_project_relationships(db, project_id, assigned_user_ids)
            self._verify_scim_project_roles(db, project_id, desired_actions, stale_user_ids)

    @staticmethod
    def _repair_project_relationships(db, project_id: SnowflakeID, user_ids: set[SnowflakeID]) -> None:
        if len(user_ids) < 2:
            return
        requested_pairs = {
            (user_id, related_user_id)
            for user_id in user_ids
            for related_user_id in user_ids
            if user_id != related_user_id
        }
        existing_pairs = set(
            db.exec(
                SqlBuilder.select.columns(
                    ProjectUserRelationship.column("user_id"),
                    ProjectUserRelationship.column("related_user_id"),
                )
                .where(ProjectUserRelationship.column("project_id") == project_id)
                .where(ProjectUserRelationship.column("user_id").in_(user_ids))
                .where(ProjectUserRelationship.column("related_user_id").in_(user_ids))
            ).all()
        )
        missing_pairs = requested_pairs - existing_pairs
        if missing_pairs:
            db.insert_all(
                [
                    ProjectUserRelationship(
                        project_id=project_id,
                        user_id=user_id,
                        related_user_id=related_user_id,
                    )
                    for user_id, related_user_id in missing_pairs
                ]
            )
        db.exec(
            SqlBuilder.update.table(ProjectUserRelationship)
            .values(last_related_at=SafeDateTime.now())
            .where(ProjectUserRelationship.column("project_id") == project_id)
            .where(ProjectUserRelationship.column("user_id").in_(user_ids))
            .where(ProjectUserRelationship.column("related_user_id").in_(user_ids))
        )

    @staticmethod
    def _verify_scim_project_roles(
        db,
        project_id: SnowflakeID,
        desired_actions: Mapping[SnowflakeID, list[str]],
        stale_user_ids: set[SnowflakeID],
    ) -> None:
        final_user_ids = set(
            db.exec(
                SqlBuilder.select.column(ProjectAssignedUser.column("user_id")).where(
                    ProjectAssignedUser.column("project_id") == project_id
                )
            ).all()
        )
        roles = {
            role.user_id: role
            for role in db.exec(
                SqlBuilder.select.table(ProjectRole).where(ProjectRole.column("project_id") == project_id)
            ).all()
        }
        for user_id, actions in desired_actions.items():
            role = roles.get(user_id)
            if user_id not in final_user_ids or role is None or set(role.actions) != set(actions):
                raise ValueError("SCIM project entitlement verification failed")
        if stale_user_ids & final_user_ids:
            raise ValueError("SCIM project entitlement revocation verification failed")

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
                    & ProjectAssignedUser.column("user_id").in_(user_ids)
                )
            )
