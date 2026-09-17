from collections.abc import Sequence
from sqlalchemy import and_, func, or_, select
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TUserParam
from ....domain.models import (
    IdentityProvider,
    ProjectAssignedUser,
    ProjectUserRelationship,
    User,
    UserEmail,
    UserIdentityLink,
    UserProfile,
)
from ....helpers import InfraHelper


class UserRepository(BaseRepository[User]):
    @staticmethod
    def model_cls():
        return User

    @staticmethod
    def name() -> str:
        return "user"

    def get_all_with_profile_in_settings(self):
        query = (
            SqlBuilder.select.tables(User, UserProfile)
            .outerjoin(UserProfile, User.column("id") == UserProfile.column("user_id"))
            .where(User.column("deleted_at") == None)  # noqa
            .order_by(User.column("created_at").desc(), User.column("id").desc())
        )

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()
        return records

    def count_not_deleted(self) -> int:
        with DbSession.use(readonly=True) as db:
            return (
                db.exec(
                    SqlBuilder.select.count(User, User.column("id")).where(User.column("deleted_at") == None)  # noqa
                ).first()
                or 0
            )

    def get_not_deleted_page(self, offset: int, limit: int) -> list[User]:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(User)
                .where(User.column("deleted_at") == None)  # noqa
                .order_by(User.column("created_at").asc(), User.column("id").asc())
                .offset(offset)
                .limit(limit)
            ).all()

    def get_by_email(self, email: str | None):
        user = InfraHelper.get_by(User, "email", email)
        if user:
            return user, None
        record = (None, None)
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(User, UserEmail)
                .join(
                    UserEmail,
                    (User.column("id") == UserEmail.column("user_id")) & (UserEmail.column("deleted_at") == None),  # noqa
                )
                .where(UserEmail.column("email") == email)
                .limit(1)
            )
            record = result.first() or (None, None)
        return record

    def search_project_member_candidates(
        self,
        user: TUserParam,
        query: str,
        can_search_all_users: bool,
        organization_identities: Sequence[tuple[IdentityProvider, str]],
        limit: int = 20,
    ) -> list[User]:
        user_id = InfraHelper.convert_id(user)
        query = query.strip().lower()
        if len(query) < 2:
            return []

        search = f"%{query}%"
        search_clause = or_(
            func.lower(User.column("email")).like(search),
            func.lower(User.column("firstname")).like(search),
            func.lower(User.column("lastname")).like(search),
            func.lower(User.column("username")).like(search),
        )

        sql = (
            SqlBuilder.select.table(User)
            .where(User.column("id") != user_id)
            .where(User.column("deleted_at") == None)  # noqa: E711
            .where(User.column("activated_at") != None)  # noqa: E711
            .where(self._has_organization_identity(organization_identities))
            .where(search_clause)
            .order_by(User.column("firstname").asc(), User.column("lastname").asc(), User.column("id").asc())
            .limit(limit)
        )

        if not can_search_all_users:
            related_project_ids = select(ProjectAssignedUser.column("project_id")).where(
                ProjectAssignedUser.column("user_id") == user_id
            )
            current_related_user_exists = (
                select(ProjectAssignedUser.column("id"))
                .where(ProjectAssignedUser.column("user_id") == User.column("id"))
                .where(ProjectAssignedUser.column("project_id").in_(related_project_ids))
                .exists()
            )
            historical_related_user_exists = (
                select(ProjectUserRelationship.column("id"))
                .where(ProjectUserRelationship.column("user_id") == user_id)
                .where(ProjectUserRelationship.column("related_user_id") == User.column("id"))
                .exists()
            )
            sql = sql.where(current_related_user_exists | historical_related_user_exists)

        with DbSession.use(readonly=True) as db:
            result = db.exec(sql)
            return result.all()

    def get_direct_project_member_candidates(
        self,
        user: TUserParam,
        candidate_users: Sequence[TUserParam],
        can_search_all_users: bool,
        organization_identities: Sequence[tuple[IdentityProvider, str]],
    ) -> list[User]:
        """Resolve only active users inside the caller's candidate relationship scope."""

        user_id = InfraHelper.convert_id(user)
        candidate_ids = list(dict.fromkeys(InfraHelper.convert_id(candidate) for candidate in candidate_users))
        if not candidate_ids:
            return []

        sql = (
            SqlBuilder.select.table(User)
            .where(User.column("id").in_(candidate_ids))
            .where(User.column("id") != user_id)
            .where(User.column("deleted_at") == None)  # noqa: E711
            .where(User.column("activated_at") != None)  # noqa: E711
            .where(self._has_organization_identity(organization_identities))
            .order_by(User.column("id").asc())
        )

        if not can_search_all_users:
            related_project_ids = select(ProjectAssignedUser.column("project_id")).where(
                ProjectAssignedUser.column("user_id") == user_id
            )
            current_related_user_exists = (
                select(ProjectAssignedUser.column("id"))
                .where(ProjectAssignedUser.column("user_id") == User.column("id"))
                .where(ProjectAssignedUser.column("project_id").in_(related_project_ids))
                .exists()
            )
            historical_related_user_exists = (
                select(ProjectUserRelationship.column("id"))
                .where(ProjectUserRelationship.column("user_id") == user_id)
                .where(ProjectUserRelationship.column("related_user_id") == User.column("id"))
                .exists()
            )
            sql = sql.where(current_related_user_exists | historical_related_user_exists)

        with DbSession.use(readonly=True) as db:
            return db.exec(sql).all()

    @staticmethod
    def _has_organization_identity(organization_identities: Sequence[tuple[IdentityProvider, str]]):
        clauses = [
            and_(
                UserIdentityLink.column("provider") == provider,
                UserIdentityLink.column("issuer") == issuer,
            )
            for provider, issuer in organization_identities
        ]
        return (
            select(UserIdentityLink.column("id"))
            .where(UserIdentityLink.column("user_id") == User.column("id"))
            .where(or_(*clauses))
            .exists()
        )
