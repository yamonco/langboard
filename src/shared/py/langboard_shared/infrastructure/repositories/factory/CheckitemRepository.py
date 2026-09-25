from sqlalchemy import case, func
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TChecklistParam, TProjectParam, TUserParam
from ....domain.models import Card, Checkitem, Checklist, Project, User
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

    def find_started_checkitem_by_user(self, user: TUserParam):
        user_id = InfraHelper.convert_id(user)
        record = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(Checkitem)
                .where(
                    (Checkitem.column("user_id") == user_id) & (Checkitem.column("status") == CheckitemStatus.Started)
                )
                .limit(1)
            )
            record = result.first()
        return record
