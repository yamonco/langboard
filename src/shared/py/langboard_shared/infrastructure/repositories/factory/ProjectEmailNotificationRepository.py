from sqlalchemy import delete
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....domain.models import Project, ProjectEmailNotificationPolicy, ProjectEmailNotificationRecipient, User
from ....domain.models.ProjectEmailNotificationPolicy import ProjectEmailNotificationCategory
from ....helpers import InfraHelper


class ProjectEmailNotificationRepository(BaseRepository[ProjectEmailNotificationPolicy]):
    @staticmethod
    def model_cls() -> type[ProjectEmailNotificationPolicy]:
        return ProjectEmailNotificationPolicy

    @staticmethod
    def name() -> str:
        return "project_email_notification"

    def get_with_recipients(
        self,
        project: TProjectParam,
    ) -> tuple[ProjectEmailNotificationPolicy | None, list[User]]:
        project_id = InfraHelper.convert_id(project)
        with DbSession.use(readonly=True) as db:
            policy = db.exec(
                SqlBuilder.select.table(ProjectEmailNotificationPolicy).where(
                    ProjectEmailNotificationPolicy.column("project_id") == project_id
                )
            ).first()
            if not policy:
                return None, []
            recipients = db.exec(
                SqlBuilder.select.table(User)
                .join(
                    ProjectEmailNotificationRecipient,
                    User.column("id") == ProjectEmailNotificationRecipient.column("user_id"),
                )
                .where(ProjectEmailNotificationRecipient.column("policy_id") == policy.id)
                .where(User.column("deleted_at") == None)  # noqa: E711
                .order_by(User.column("firstname").asc(), User.column("lastname").asc(), User.column("id").asc())
            ).all()
            return policy, recipients

    def replace(
        self,
        project: Project,
        *,
        is_enabled: bool,
        notify_all_members: bool,
        categories: list[ProjectEmailNotificationCategory],
        card_move_target_columns: list[str],
        recipient_user_ids: list[SnowflakeID],
    ) -> ProjectEmailNotificationPolicy:
        """Replace policy and recipients atomically."""

        with DbSession.use(readonly=False) as db:
            policy = db.exec(
                SqlBuilder.select.table(ProjectEmailNotificationPolicy).where(
                    ProjectEmailNotificationPolicy.column("project_id") == project.id
                )
            ).first()
            if policy is None:
                policy = ProjectEmailNotificationPolicy(
                    project_id=project.id,
                    is_enabled=is_enabled,
                    notify_all_members=notify_all_members,
                    categories=categories,
                    card_move_target_columns=card_move_target_columns,
                )
                db.insert(policy)
            else:
                policy.is_enabled = is_enabled
                policy.notify_all_members = notify_all_members
                policy.categories = categories
                policy.card_move_target_columns = card_move_target_columns
                db.update(policy)

            db.exec(
                delete(ProjectEmailNotificationRecipient.__table__).where(
                    ProjectEmailNotificationRecipient.column("policy_id") == policy.id
                )
            )
            db.insert_all(
                ProjectEmailNotificationRecipient(policy_id=policy.id, user_id=user_id)
                for user_id in recipient_user_ids
            )
            return policy
