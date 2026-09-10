from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TScimGroupParam, TUserParam
from ....domain.models import ScimGroup, ScimGroupMember, User
from ....helpers import InfraHelper


class ScimGroupMemberRepository(BaseRepository[ScimGroupMember]):
    @staticmethod
    def model_cls():
        return ScimGroupMember

    @staticmethod
    def name() -> str:
        return "scim_group_member"

    def get_users_by_group(
        self, group: TScimGroupParam, *, consistent: bool = False
    ) -> list[tuple[ScimGroupMember, User]]:
        group_id = InfraHelper.convert_id(group)

        with DbSession.use(readonly=not consistent) as db:
            return db.exec(
                SqlBuilder.select.tables(ScimGroupMember, User)
                .join(User, User.column("id") == ScimGroupMember.column("user_id"))
                .where(ScimGroupMember.column("group_id") == group_id)
                .order_by(User.column("email").asc(), User.column("id").asc())
            ).all()

    def get_users_by_groups(self, group_ids: list[SnowflakeID]) -> list[tuple[ScimGroupMember, User]]:
        if not group_ids:
            return []

        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.tables(ScimGroupMember, User)
                .join(User, User.column("id") == ScimGroupMember.column("user_id"))
                .where(ScimGroupMember.column("group_id").in_(group_ids))
                .order_by(ScimGroupMember.column("group_id").asc(), User.column("email").asc(), User.column("id").asc())
            ).all()

    def get_groups_by_user(
        self, user: TUserParam, *, consistent: bool = False
    ) -> list[tuple[ScimGroupMember, ScimGroup]]:
        user_id = InfraHelper.convert_id(user)

        with DbSession.use(readonly=not consistent) as db:
            return db.exec(
                SqlBuilder.select.tables(ScimGroupMember, ScimGroup)
                .join(ScimGroup, ScimGroup.column("id") == ScimGroupMember.column("group_id"))
                .where(ScimGroupMember.column("user_id") == user_id)
                .order_by(ScimGroup.column("external_id").asc(), ScimGroup.column("id").asc())
            ).all()

    def delete_all_by_group(self, group: TScimGroupParam) -> None:
        group_id = InfraHelper.convert_id(group)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ScimGroupMember).where(ScimGroupMember.column("group_id") == group_id),
                purge=True,
            )

    def delete_all_by_user(self, user: TUserParam) -> None:
        user_id = InfraHelper.convert_id(user)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ScimGroupMember).where(ScimGroupMember.column("user_id") == user_id),
                purge=True,
            )

    def replace_group_members(self, group: TScimGroupParam, user_ids: list[SnowflakeID]) -> None:
        group_id = InfraHelper.convert_id(group)
        deduped_user_ids = list(dict.fromkeys(user_ids))

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ScimGroupMember).where(ScimGroupMember.column("group_id") == group_id),
                purge=True,
            )
            for user_id in deduped_user_ids:
                db.insert(ScimGroupMember(group_id=group_id, user_id=user_id))
