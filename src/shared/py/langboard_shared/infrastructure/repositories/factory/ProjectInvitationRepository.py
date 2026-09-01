from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....domain.models import Project, ProjectInvitation, User, UserEmail
from ....helpers import InfraHelper


class ProjectInvitationRepository(BaseRepository[ProjectInvitation]):
    @staticmethod
    def model_cls():
        return ProjectInvitation

    @staticmethod
    def name() -> str:
        return "project_invitation"

    def get_all_by_project(self, project: TProjectParam) -> list[ProjectInvitation]:
        project_id = InfraHelper.convert_id(project)
        invitations = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectInvitation).where(ProjectInvitation.column("project_id") == project_id)
            )
            invitations = result.all()
        return invitations

    def get_all_by_project_with_user(self, project: TProjectParam) -> list[tuple[ProjectInvitation, User | None]]:
        project_id = InfraHelper.convert_id(project)
        users = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(ProjectInvitation, User)
                .outerjoin(
                    UserEmail,
                    (ProjectInvitation.column("email") == UserEmail.column("email"))
                    & (UserEmail.column("deleted_at") == None),  # noqa
                )
                .outerjoin(
                    User,
                    (User.column("email") == ProjectInvitation.column("email"))
                    | (User.column("id") == UserEmail.column("user_id")),
                )
                .where(ProjectInvitation.column("project_id") == project_id)
            )
            users = result.all()
        return list(users)

    def get_by_id_and_token(self, invitation_id: SnowflakeID, token: str) -> ProjectInvitation | None:
        invitation = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectInvitation)
                .where((ProjectInvitation.column("id") == invitation_id) & (ProjectInvitation.column("token") == token))
                .limit(1)
            )
            invitation = result.first()
        return invitation

    def get_by_project_and_email(self, project: TProjectParam, email: str) -> ProjectInvitation | None:
        project_id = InfraHelper.convert_id(project)
        invitation = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectInvitation)
                .where(
                    (ProjectInvitation.column("project_id") == project_id)
                    & (ProjectInvitation.column("email") == email)
                )
                .limit(1)
            )
            invitation = result.first()
        return invitation

    def get_all_with_projects_by_email(self, email: str) -> list[tuple[ProjectInvitation, Project]]:
        invitations = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(ProjectInvitation, Project)
                .join(
                    Project,
                    ProjectInvitation.column("project_id") == Project.column("id"),
                )
                .where(
                    (ProjectInvitation.column("email") == email) & (ProjectInvitation.column("token") != None)  # noqa
                )
            )
            invitations = result.all()
        return invitations
