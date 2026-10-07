from datetime import timedelta
from typing import Literal
from dateutil.relativedelta import relativedelta
from sqlalchemy import BigInteger, String, and_, false, func, literal, literal_column, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TUserParam
from ....domain.models import (
    Card,
    CardComment,
    Checkitem,
    Checklist,
    Project,
    ProjectAssignedUser,
    ProjectInvitation,
    ProjectWiki,
    ProjectWikiAssignedUser,
    UserNotification,
)
from ....domain.models.UserNotification import NotificationType
from ....domain.services.CardVisibilityPolicy import CardVisibilityContext, card_visibility_scope
from ....helpers import InfraHelper


class UserNotificationRepository(BaseRepository[UserNotification]):
    @staticmethod
    def model_cls():
        return UserNotification

    @staticmethod
    def name() -> str:
        return "user_notification"

    def get_scoped_list(
        self, user: TUserParam, time_range: Literal["3d", "7d", "1m", "all"],
        page: int, limit: int, unread_only: bool, *, contexts: dict[int, CardVisibilityContext],
    ) -> tuple[list[UserNotification], int]:
        """Authorize every JSON reference before notification pages and unread counts."""
        user_id = InfraHelper.convert_id(user)
        dialect = DbEngine.get_main_engine().dialect.name
        if dialect == "sqlite":
            refs = func.json_each(UserNotification.record_list).table_valued("key", "value").alias("notification_refs")
            table = func.json_extract(refs.c.value, "$[0]")
            record_id = func.json_extract(refs.c.value, "$[1]")
        elif dialect == "postgresql":
            refs = func.jsonb_array_elements(sql_cast(UserNotification.record_list, JSONB)).table_valued("value").alias("notification_refs")
            table = refs.c.value.op("->>")(0)
            record_id = sql_cast(refs.c.value.op("->>")(1), BigInteger)
        elif dialect in {"mysql", "mariadb"}:
            refs = func.JSON_TABLE(
                UserNotification.record_list,
                literal_column("'$[*]' COLUMNS (ref_table VARCHAR(64) PATH '$[0]', ref_id BIGINT PATH '$[1]')"),
            ).table_valued("ref_table", "ref_id").alias("notification_refs")
            table, record_id = refs.c.ref_table, refs.c.ref_id
        else:
            # Unimplemented dialects must not fall back to an unscoped list.
            return [], 0
        grouped: dict[CardVisibilityContext, list[int]] = {}
        for project_id, context in contexts.items():
            grouped.setdefault(context, []).append(project_id)
        card_scope = or_(false(), *(
            Card.project_id.in_(ids) & card_visibility_scope(context)
            for context, ids in grouped.items()
        ))
        def visible_card(card_id):
            return select(Card.id).where(Card.id == card_id, Card.deleted_at.is_(None), card_scope).correlate_except(Card).exists()
        project_visible = select(Project.id).where(
            Project.id == record_id, Project.deleted_at.is_(None),
            or_(Project.id.in_(list(contexts)), UserNotification.notification_type == NotificationType.ProjectInvited),
        ).correlate(refs, UserNotification).exists()
        allowed = [and_(table == "project", project_visible), and_(table == "card", visible_card(record_id))]
        for model in (CardComment, Checklist):
            allowed.append(and_(table == model.__tablename__, select(model.id).where(
                model.id == record_id, model.deleted_at.is_(None), visible_card(model.card_id),
            ).correlate(refs).exists()))
        allowed.append(and_(table == "checkitem", select(Checkitem.id).join(Checklist, Checklist.id == Checkitem.checklist_id).where(
            Checkitem.id == record_id, Checkitem.deleted_at.is_(None), Checklist.deleted_at.is_(None), visible_card(Checklist.card_id),
        ).correlate(refs).exists()))
        wiki_assigned = select(ProjectWikiAssignedUser.id).where(
            ProjectWikiAssignedUser.project_wiki_id == ProjectWiki.id, ProjectWikiAssignedUser.user_id == user_id,
        ).exists()
        wiki_visible = select(ProjectWiki.id).join(Project, Project.id == ProjectWiki.project_id).where(
            ProjectWiki.id == record_id, ProjectWiki.deleted_at.is_(None), ProjectWiki.project_id.in_(list(contexts)),
            or_(ProjectWiki.is_public.is_(True), Project.owner_id == user_id, wiki_assigned),
        ).correlate(refs).exists()
        allowed.append(and_(table == "project_wiki", wiki_visible))
        invitation_visible = select(ProjectInvitation.id).join(Project, Project.id == ProjectInvitation.project_id).where(
            ProjectInvitation.id == record_id, Project.deleted_at.is_(None),
            UserNotification.notification_type == NotificationType.ProjectInvited,
        ).correlate(refs, UserNotification).exists()
        allowed.append(and_(table == "project_invitation", invitation_visible))
        invalid_reference = select(literal(1)).select_from(refs).where(~func.coalesce(or_(*allowed), false())).correlate(UserNotification).exists()
        has_reference = select(literal(1)).select_from(refs).correlate(UserNotification).exists()
        def scoped(query):
            query = query.where(UserNotification.receiver_id == user_id, UserNotification.web_visible.is_(True),
                                has_reference, ~invalid_reference)
            if time_range.endswith("d"):
                query = query.where(UserNotification.created_at >= SafeDateTime.now() - timedelta(days=int(time_range[:-1])))
            elif time_range.endswith("m"):
                query = query.where(UserNotification.created_at >= SafeDateTime.now() - relativedelta(months=int(time_range[:-1])))
            return query
        with DbSession.use(readonly=False) as db:
            unread = db.exec(scoped(SqlBuilder.select.count(UserNotification, UserNotification.id)).where(
                UserNotification.read_at.is_(None),
            )).first() or 0
            query = scoped(SqlBuilder.select.table(UserNotification))
            if unread_only:
                query = query.where(UserNotification.read_at.is_(None))
            return list(db.exec(query.order_by(UserNotification.created_at.desc(), UserNotification.id.desc()).limit(
                limit + 1,
            ).offset((page - 1) * limit)).all()), unread

    def get_list(
        self,
        user: TUserParam,
        time_range: Literal["3d", "7d", "1m", "all"] = "3d",
        page: int = 1,
        limit: int = 20,
        unread_only: bool = False,
        authorized_projects_only: bool = False,
    ):
        """Return one ordered notification page for a user."""

        user_id = InfraHelper.convert_id(user)
        query = (
            SqlBuilder.select.table(UserNotification)
            .where(UserNotification.column("receiver_id") == user_id)
            .where(UserNotification.column("web_visible") == True)  # noqa: E712
        )

        if unread_only:
            query = query.where(UserNotification.column("read_at") == None)  # noqa

        if authorized_projects_only:
            record_list_text = sql_cast(UserNotification.column("record_list"), String)
            project_id_text = sql_cast(ProjectAssignedUser.column("project_id"), String)
            authorized_project = (
                select(ProjectAssignedUser.column("id"))
                .join(Project, ProjectAssignedUser.column("project_id") == Project.column("id"))
                .where(ProjectAssignedUser.column("user_id") == user_id)
                .where(Project.column("deleted_at") == None)  # noqa: E711
                .where(
                    or_(
                        record_list_text.like(literal('%["project", ') + project_id_text + literal("]%")),
                        record_list_text.like(literal('%["project",') + project_id_text + literal("]%")),
                    )
                )
                .exists()
            )
            query = query.where(
                or_(
                    UserNotification.column("notification_type") == NotificationType.ProjectInvited,
                    authorized_project,
                )
            )

        if time_range.endswith("d"):
            days = int(time_range[:-1])
            query = query.where(UserNotification.column("created_at") >= SafeDateTime.now() - timedelta(days=days))
        elif time_range.endswith("m"):
            month = int(time_range[:-1])
            query = query.where(
                UserNotification.column("created_at") >= SafeDateTime.now() - relativedelta(months=month)
            )

        query = query.order_by(
            UserNotification.column("created_at").desc(),
            UserNotification.column("id").desc(),
        )
        query = query.limit(limit + 1).offset((page - 1) * limit)

        notifications = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            notifications = result.all()

        return notifications

    def get_project_invitation_notification(self, user: TUserParam, record_list: str) -> UserNotification | None:
        user_id = InfraHelper.convert_id(user)
        notification = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(UserNotification)
                .where(
                    (UserNotification.column("receiver_id") == user_id)
                    & (UserNotification.column("notification_type") == NotificationType.ProjectInvited)
                    & (sql_cast(UserNotification.column("record_list"), String) == record_list)
                )
                .limit(1)
            )
            notification = result.first()
        return notification

    def get_pending_work_events(self, limit: int = 100) -> list[UserNotification]:
        """Read a bounded durable work-event backlog from the primary database."""

        eligible_types = [
            NotificationType.AssignedToCard,
            NotificationType.MentionedInCard,
            NotificationType.MentionedInComment,
            NotificationType.MentionedInWiki,
            NotificationType.NotifiedFromChecklist,
            NotificationType.ProjectInvited,
            NotificationType.ScheduledRule,
        ]
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(UserNotification)
                .where(UserNotification.column("notification_type").in_(eligible_types))
                .where(UserNotification.column("work_event_dispatched_at") == None)  # noqa: E711
                .order_by(UserNotification.column("created_at").asc(), UserNotification.column("id").asc())
                .limit(max(1, min(limit, 100)))
            ).all()

    def mark_work_event_dispatched(self, notification: UserNotification) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(UserNotification)
                .values(work_event_dispatched_at=SafeDateTime.now())
                .where(UserNotification.column("id") == notification.id)
                .where(UserNotification.column("work_event_dispatched_at") == None)  # noqa: E711
            )

    def count_unread(
        self, user: TUserParam, time_range: Literal["3d", "7d", "1m", "all"] = "all"
    ) -> int:
        user_id = InfraHelper.convert_id(user)
        query = SqlBuilder.select.count(UserNotification, UserNotification.column("id")).where(
            (UserNotification.column("receiver_id") == user_id)
            & (UserNotification.column("web_visible") == True)  # noqa: E712
            & (UserNotification.column("read_at") == None)  # noqa: E711
        )
        if time_range.endswith("d"):
            query = query.where(
                UserNotification.column("created_at") >= SafeDateTime.now() - timedelta(days=int(time_range[:-1]))
            )
        elif time_range.endswith("m"):
            query = query.where(
                UserNotification.column("created_at") >= SafeDateTime.now() - relativedelta(months=int(time_range[:-1]))
            )

        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            return result.first() or 0

    def get_mentioned_card_ids(self, user: TUserParam, limit: int = 500) -> list[int]:
        """Return recent card ids mentioned in notifications for one receiver."""

        user_id = InfraHelper.convert_id(user)
        notifications = []
        with DbSession.use(readonly=True) as db:
            notifications = db.exec(
                SqlBuilder.select.table(UserNotification)
                .where(UserNotification.column("receiver_id") == user_id)
                .where(UserNotification.column("web_visible") == True)  # noqa: E712
                .where(
                    UserNotification.column("notification_type").in_(
                        [NotificationType.MentionedInCard, NotificationType.MentionedInComment]
                    )
                )
                .order_by(UserNotification.column("created_at").desc(), UserNotification.column("id").desc())
                .limit(max(1, min(limit, 500)))
            ).all()

        card_ids: list[int] = []
        for notification in notifications:
            for table_name, record_id in notification.record_list:
                if table_name == "card":
                    card_ids.append(record_id)
        return card_ids

    def read_all_by_user(self, user: TUserParam):
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(UserNotification)
                .values({UserNotification.column("read_at"): SafeDateTime.now()})
                .where(
                    (UserNotification.column("receiver_id") == user_id)
                    & (UserNotification.column("web_visible") == True)  # noqa: E712
                    & (UserNotification.column("read_at") == None)  # noqa: E711
                )
            )

    def delete_all(self, user: TUserParam):
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=False) as db:
            db.exec(SqlBuilder.delete.table(UserNotification).where(UserNotification.column("receiver_id") == user_id))

    def delete_all_by_ids(self, notification_ids: list[int]):
        if not notification_ids:
            return
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(UserNotification).where(UserNotification.column("id").in_(notification_ids))
            )
