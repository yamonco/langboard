from sqlalchemy import func
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TColumnParam, TProjectParam, TUserParam
from ....domain.models import Card, CardAssignedUser, CardComment, Project, ProjectColumn, ProjectRole
from ....helpers import InfraHelper


class CardRepository(BaseOrderRepository[Card, ProjectColumn]):
    @staticmethod
    def parent_model_cls():
        return ProjectColumn

    @staticmethod
    def model_cls():
        return Card

    @staticmethod
    def name() -> str:
        return "card"

    def get_by_id_like(self, card: TCardParam | None) -> Card | None:
        return InfraHelper.get_by_id_like(Card, card)

    def get_board_list(self, project: TProjectParam) -> list[tuple[Card, int]]:
        project_id = InfraHelper.convert_id(project)
        comment_counts = (
            SqlBuilder.select.columns(
                CardComment.column("card_id"),
                func.count(CardComment.column("id")).label("count_comment"),  # type: ignore
            )
            .join(Card, Card.column("id") == CardComment.column("card_id"))
            .where(Card.column("project_id") == project_id)
            .group_by(CardComment.column("card_id"))
            .subquery()
        )

        cards = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(Card, func.coalesce(comment_counts.c.count_comment, 0).label("count_comment"))  # type: ignore
                .outerjoin(comment_counts, Card.column("id") == comment_counts.c.card_id)
                .where(Card.column("project_id") == project_id)
                .order_by(Card.column("order").asc())
            )
            cards = result.all()

        return cards

    def get_dashboard_list_scroller(self, user: TUserParam, pagination: TimeBasedPagination):
        user_id = InfraHelper.convert_id(user)
        query = (
            SqlBuilder.select.tables(Card, Project, ProjectColumn)
            .join(Project, Card.column("project_id") == Project.column("id"))
            .join(
                ProjectColumn,
                (Card.column("project_column_id") == ProjectColumn.column("id"))
                & (ProjectColumn.column("project_id") == Project.column("id")),
            )
            .join(ProjectRole, Project.column("id") == ProjectRole.column("project_id"))
            .outerjoin(
                CardAssignedUser,
                Card.column("id") == CardAssignedUser.column("card_id"),
            )
            .where(
                (ProjectRole.column("user_id") == user_id)
                & (
                    (
                        (ProjectRole.column("actions") == "*")
                        & (
                            (CardAssignedUser.column("card_id") == None)  # noqa
                            | (CardAssignedUser.column("user_id") == user_id)
                        )
                    )
                    | ((ProjectRole.column("actions") != "*") & (CardAssignedUser.column("user_id") == user_id))
                )
            )
            .where(Card.column("created_at") <= pagination.refer_time)
            .order_by(Card.column("created_at").desc(), Card.column("id").desc())
        )
        query = InfraHelper.paginate(query, pagination.page, pagination.limit)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()
        return records

    def get_all_by_project(self, project: TProjectParam):
        project_id = InfraHelper.convert_id(project)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(Card, ProjectColumn)
                .join(
                    ProjectColumn,
                    Card.column("project_column_id") == ProjectColumn.column("id"),
                )
                .where(Card.column("project_id") == project_id)
                .order_by(Card.column("order").asc())
            )
            records = result.all()
        return records

    def get_page_by_project(
        self,
        project: TProjectParam,
        limit: int,
        before_updated_at: SafeDateTime | None = None,
        before_card: TCardParam | None = None,
    ) -> list[tuple[Card, ProjectColumn]]:
        """Return a bounded newest-updated-first project-card keyset page."""

        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.tables(Card, ProjectColumn)
            .join(ProjectColumn, Card.column("project_column_id") == ProjectColumn.column("id"))
            .where(Card.column("project_id") == project_id)
        )
        if before_updated_at is not None:
            if before_card is None:
                raise ValueError("before_card is required with before_updated_at")
            before_card_id = InfraHelper.convert_id(before_card)
            query = query.where(
                (Card.column("updated_at") < before_updated_at)
                | ((Card.column("updated_at") == before_updated_at) & (Card.column("id") < before_card_id))
            )
        query = query.order_by(Card.column("updated_at").desc(), Card.column("id").desc()).limit(limit + 1)
        with DbSession.use(readonly=True) as db:
            return list(db.exec(query).all())

    def count_by_project(self, project: TProjectParam) -> int:
        """Count cards in one project without materializing them."""

        project_id = InfraHelper.convert_id(project)
        with DbSession.use(readonly=True) as db:
            return (
                db.exec(
                    SqlBuilder.select.count(Card, Card.column("id")).where(Card.column("project_id") == project_id)
                ).first()
                or 0
            )

    def get_all_by_column(self, column: TColumnParam):
        column_id = InfraHelper.convert_id(column)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(Card)
                .where(Card.column("project_column_id") == column_id)
                .order_by(Card.column("order").asc())
            )
            records = result.all()
        return records

    def move_all_by_column(
        self,
        source_column: TColumnParam,
        dest_column: TColumnParam,
        count_cards_in_dest_column: int,
        is_archive: bool = False,
    ):
        source_column_id = InfraHelper.convert_id(source_column)
        dest_column_id = InfraHelper.convert_id(dest_column)
        current_time = SafeDateTime.now()

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.update.table(Card)
                .values({Card.order: Card.order + count_cards_in_dest_column})
                .where(Card.column("project_column_id") == dest_column_id)
            )

            ordered_cards_cte = (
                SqlBuilder.select.columns(
                    Card.column("id"),
                    (func.row_number().over(order_by=Card.column("order")) - 1).label("new_order"),
                )
                .where(Card.column("project_column_id") == source_column_id)
                .cte("ordered_cards")
            )

            db.exec(
                SqlBuilder.update.table(Card)
                .filter(Card.column("id") == ordered_cards_cte.c.id)
                .values(
                    {
                        Card.column("order"): ordered_cards_cte.c.new_order,
                        Card.column("project_column_id"): dest_column_id,
                        Card.column("archived_at"): current_time if is_archive else None,
                    }
                )
            )
