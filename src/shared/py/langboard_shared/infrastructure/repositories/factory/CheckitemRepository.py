from sqlalchemy import case, func, select
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TChecklistParam, TProjectParam, TUserParam
from ....domain.models import Card, Checkitem, CheckitemTimerRecord, Checklist, Project, User
from ....domain.models.Checkitem import CheckitemStatus
from ....helpers import InfraHelper


class CheckitemRepository(BaseOrderRepository[Checkitem, Checklist]):
    def get_board_progress_by_project(
        self, project: TProjectParam, archive_visible_since: SafeDateTime
    ) -> dict[int, tuple[int, int]]:
        """Return user-checklist counts without loading checkitems into the board payload."""

        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.columns(
                Checklist.column("card_id"),
                func.count(Checkitem.column("id")),
                func.sum(case((Checkitem.column("is_checked") == True, 1), else_=0)),  # noqa: E712
            )
            .join(Checklist, Checkitem.column("checklist_id") == Checklist.column("id"))
            .join(Card, Checklist.column("card_id") == Card.column("id"))
            .where(Card.column("project_id") == project_id)
            .where(
                (Card.column("archived_at") == None)  # noqa: E711
                | (Card.column("archived_at") >= archive_visible_since)
            )
            .where(Checklist.column("is_system") == False)  # noqa: E712
            .where(Checklist.column("deleted_at") == None)  # noqa: E711
            .where(Checkitem.column("deleted_at") == None)  # noqa: E711
            .group_by(Checklist.column("card_id"))
        )
        with DbSession.use(readonly=True) as db:
            return {card_id: (int(total), int(completed or 0)) for card_id, total, completed in db.exec(query).all()}

    def get_active_workers_by_project(
        self, project: TProjectParam, card: TCardParam | None = None
    ) -> list[tuple[Checkitem, Checklist, SafeDateTime | None]]:
        """Fetch active timer owners and latest timer anchors in two bounded queries."""
        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.tables(Checkitem, Checklist)
            .join(Checklist, Checkitem.column("checklist_id") == Checklist.column("id"))
            .join(Card, Checklist.column("card_id") == Card.column("id"))
            .where(Card.column("project_id") == project_id)
            .where(Card.column("archived_at") == None)  # noqa: E711
            .where(Checklist.column("is_system") == False)  # noqa: E712
            .where(Checklist.column("deleted_at") == None)  # noqa: E711
            .where(Checkitem.column("deleted_at") == None)  # noqa: E711
            .where(Checkitem.column("is_checked") == False)  # noqa: E712
            .where(Checkitem.column("user_id").is_not(None))
            .where(Checkitem.column("status").in_([CheckitemStatus.Started, CheckitemStatus.Paused]))
            .order_by(Checklist.column("card_id"), Checkitem.column("user_id"), Checkitem.column("order"))
        )
        if card is not None:
            query = query.where(Card.column("id") == InfraHelper.convert_id(card))
        with DbSession.use(readonly=True) as db:
            workers = list(db.exec(query).all())
            if not workers:
                return []
            item_ids = [checkitem.id for checkitem, _ in workers]
            latest = (
                select(
                    CheckitemTimerRecord.column("checkitem_id"),
                    func.max(CheckitemTimerRecord.column("id")).label("latest_id"),
                )
                .where(CheckitemTimerRecord.column("checkitem_id").in_(item_ids))
                .group_by(CheckitemTimerRecord.column("checkitem_id"))
                .subquery()
            )
            timer_query = SqlBuilder.select.table(CheckitemTimerRecord).join(
                latest, CheckitemTimerRecord.column("id") == latest.c.latest_id
            )
            latest_timer = {record.checkitem_id: record for record in db.exec(timer_query).all()}
        return [
            (
                checkitem,
                checklist,
                SafeDateTime.fromisoformat(latest_timer[checkitem.id].created_at.isoformat())
                if checkitem.status == CheckitemStatus.Started and checkitem.id in latest_timer
                else None,
            )
            for checkitem, checklist in workers
        ]

    @staticmethod
    def parent_model_cls():
        return Checklist

    @staticmethod
    def model_cls():
        return Checkitem

    @staticmethod
    def name() -> str:
        return "checkitem"

    def get_all_by_checklist(
        self, checklist: TChecklistParam, limit: int | None = None
    ) -> list[tuple[Checkitem, Card | None, User | None]]:
        """Return checklist items, optionally enforcing a database row limit."""

        checklist_id = InfraHelper.convert_id(checklist)

        records = []
        query = (
            SqlBuilder.select.tables(Checkitem, Card, User)
            .outerjoin(Card, Card.column("id") == Checkitem.column("cardified_id"))
            .outerjoin(User, User.column("id") == Checkitem.column("user_id"))
            .where(Checkitem.column("checklist_id") == checklist_id)
            .order_by(Checkitem.column("order").asc(), Checkitem.column("id").asc())
        )
        if limit is not None:
            query = query.limit(limit)
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()
        return list(records)

    def get_all_by_card(self, card: TCardParam) -> list[tuple[Checkitem, Card | None, User | None]]:
        card_id = InfraHelper.convert_id(card)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(Checkitem, Card, User)
                .join(
                    Checklist,
                    Checkitem.column("checklist_id") == Checklist.column("id"),
                )
                .outerjoin(Card, Card.column("id") == Checkitem.column("cardified_id"))
                .outerjoin(User, User.column("id") == Checkitem.column("user_id"))
                .where(Checklist.column("card_id") == card_id)
            )
            records = result.all()
        return list(records)

    def get_all_tracking_scroller(self, user: TUserParam, pagination: TimeBasedPagination):
        user_id = InfraHelper.convert_id(user)
        query = (
            SqlBuilder.select.tables(Checkitem, Card, Project)
            .join(Checklist, Checklist.column("id") == Checkitem.column("checklist_id"))
            .join(Card, Card.column("id") == Checklist.column("card_id"))
            .join(Project, Project.column("id") == Card.column("project_id"))
            .where((Checkitem.column("user_id") == user_id) & (Checkitem.column("created_at") <= pagination.refer_time))
            .order_by(Checkitem.column("created_at").desc(), Checkitem.column("id").desc())
        )
        query = InfraHelper.paginate(query, pagination.page, pagination.limit)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()
        return list(records)

    def get_all_started_checkitem_by_project(self, project: TProjectParam):
        project_id = InfraHelper.convert_id(project)
        checkitems = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(Checkitem, Card)
                .join(
                    Checklist,
                    Checkitem.column("checklist_id") == Checklist.column("id"),
                )
                .join(Card, Checklist.column("card_id") == Card.column("id"))
                .where(
                    (Card.column("project_id") == project_id) & (Checkitem.column("status") == CheckitemStatus.Started)
                )
            )
            checkitems = result.all()
        return checkitems

    def get_all_started_checkitem_by_card(self, card: TCardParam):
        card_id = InfraHelper.convert_id(card)
        checkitems = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(Checkitem)
                .join(
                    Checklist,
                    Checkitem.column("checklist_id") == Checklist.column("id"),
                )
                .where(
                    (Checklist.column("card_id") == card_id) & (Checkitem.column("status") == CheckitemStatus.Started)
                )
            )
            checkitems = result.all()
        return checkitems

    def get_started_work_by_user(self, user: TUserParam) -> list[tuple[Checkitem, Card, Project]]:
        user_id = InfraHelper.convert_id(user)
        query = (
            SqlBuilder.select.tables(Checkitem, Card, Project)
            .join(Checklist, Checklist.column("id") == Checkitem.column("checklist_id"))
            .join(Card, Card.column("id") == Checklist.column("card_id"))
            .join(Project, Project.column("id") == Card.column("project_id"))
            .where((Checkitem.column("user_id") == user_id) & (Checkitem.column("status") == CheckitemStatus.Started))
            .order_by(Checkitem.column("updated_at").desc(), Checkitem.column("id").desc())
        )
        with DbSession.use(readonly=True) as db:
            return list(db.exec(query).all())

    def find_started_checkitem_by_user(self, user: TUserParam):
        records = self.get_started_work_by_user(user)
        return records[0][0] if records else None
