from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TUserParam, TWikiParam
from ....domain.models import ProjectWikiAssignedUser, User
from ....helpers import InfraHelper


class ProjectWikiAssignedUserRepository(BaseRepository[ProjectWikiAssignedUser]):
    @staticmethod
    def model_cls():
        return ProjectWikiAssignedUser

    @staticmethod
    def name() -> str:
        return "project_wiki_assigned_user"

    def get_all_by_wiki(self, wiki: TWikiParam) -> list[tuple[User, ProjectWikiAssignedUser]]:
        wiki_id = InfraHelper.convert_id(wiki)
        users = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(User, ProjectWikiAssignedUser)
                .join(
                    ProjectWikiAssignedUser,
                    User.column("id") == ProjectWikiAssignedUser.column("user_id"),
                )
                .where(ProjectWikiAssignedUser.column("project_wiki_id") == wiki_id)
            )
            users = result.all()
        return users

    def find_by_user_and_wiki(self, user: TUserParam, wiki: TWikiParam):
        user_id = InfraHelper.convert_id(user)
        wiki_id = InfraHelper.convert_id(wiki)

        record = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectWikiAssignedUser)
                .where(
                    (ProjectWikiAssignedUser.column("project_wiki_id") == wiki_id)
                    & (ProjectWikiAssignedUser.column("user_id") == user_id)
                )
                .limit(1)
            )
            record = result.first()
        return record

    def get_assigned_wiki_ids(self, user: TUserParam, wiki_ids: set[int]) -> set[int]:
        if not wiki_ids:
            return set()
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=True) as db:
            records = db.exec(
                SqlBuilder.select.column(ProjectWikiAssignedUser.column("project_wiki_id"))
                .where(ProjectWikiAssignedUser.column("user_id") == user_id)
                .where(ProjectWikiAssignedUser.column("project_wiki_id").in_(wiki_ids))
            ).all()
        return {int(record) for record in records}

    def delete_all_by_wiki(self, wiki: TWikiParam) -> None:
        wiki_id = InfraHelper.convert_id(wiki)
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(ProjectWikiAssignedUser).where(
                    ProjectWikiAssignedUser.column("project_wiki_id") == wiki_id
                )
            )
