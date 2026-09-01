from typing import Any
from sqlalchemy import and_, or_, select
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....domain.models import Card, GraphApprovalRequest, Project, ProjectColumn, ProjectWiki
from ....domain.models.bases import BaseGraphApprovalRequestModel
from ....domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from ....helpers import InfraHelper, ModelHelper


class GraphApprovalRequestRepository(BaseRepository[GraphApprovalRequest]):
    @staticmethod
    def model_cls():
        return GraphApprovalRequest

    @staticmethod
    def name() -> str:
        return "graph_approval_request"

    def get_by_id_like(self, approval: GraphApprovalRequest | str | int) -> GraphApprovalRequest | None:
        return InfraHelper.get_by_id_like(GraphApprovalRequest, approval)

    def get_model_class(self, origin_type: GraphApprovalOriginType) -> type[BaseGraphApprovalRequestModel] | None:
        for model_class in self.__get_model_classes():
            if model_class.get_request_type() == origin_type:
                return model_class
        return None

    def get_detail(self, approval: GraphApprovalRequest | str | int) -> BaseGraphApprovalRequestModel | None:
        approval_id = InfraHelper.convert_id(approval)
        with DbSession.use(readonly=True) as db:
            for detail_class in self.__get_model_classes():
                detail = db.exec(
                    SqlBuilder.select.table(detail_class)
                    .where(detail_class.column("approval_request_id") == approval_id)
                    .limit(1)
                ).first()
                if detail:
                    return detail
        return None

    def insert_with_detail(self, approval: GraphApprovalRequest, detail: BaseGraphApprovalRequestModel) -> None:
        with DbSession.use(readonly=False) as db:
            db.insert(approval)
            detail.approval_request_id = approval.id
            db.insert(detail)

    def get_all_ordered(
        self, status: GraphApprovalStatus | None = None, origin_type: GraphApprovalOriginType | None = None
    ) -> list[GraphApprovalRequest]:
        query = SqlBuilder.select.table(GraphApprovalRequest)
        if status:
            query = query.where(GraphApprovalRequest.column("status") == status.value)
        if origin_type:
            query = query.where(GraphApprovalRequest.column("request_type") == origin_type.value)

        query = query.order_by(
            GraphApprovalRequest.column("created_at").desc(),
            GraphApprovalRequest.column("id").desc(),
        )

        with DbSession.use(readonly=True) as db:
            return db.exec(query).all()

    def get_expired_pending(self) -> list[GraphApprovalRequest]:
        query = (
            SqlBuilder.select.table(GraphApprovalRequest)
            .where(GraphApprovalRequest.column("status") == GraphApprovalStatus.Pending.value)
            .where(GraphApprovalRequest.column("expires_at").is_not(None))
            .where(GraphApprovalRequest.column("expires_at") <= SafeDateTime.now())
            .order_by(GraphApprovalRequest.column("expires_at").asc())
            .limit(500)
        )
        with DbSession.use(readonly=True) as db:
            return db.exec(query).all()

    def get_ordered_by_project(
        self,
        project_id: int,
        status: GraphApprovalStatus | None = None,
        origin_type: GraphApprovalOriginType | None = None,
        scope_table: str | None = None,
        scope_id: int | None = None,
        limit: int = 100,
    ) -> list[tuple[GraphApprovalRequest, BaseGraphApprovalRequestModel]]:
        records: list[tuple[GraphApprovalRequest, BaseGraphApprovalRequestModel]] = []
        for detail_class in self.__get_model_classes():
            if origin_type and detail_class.get_request_type() != origin_type:
                continue
            query = (
                SqlBuilder.select.tables(GraphApprovalRequest, detail_class)
                .join(
                    detail_class,
                    detail_class.column("approval_request_id") == GraphApprovalRequest.column("id"),
                )
                .where(self.__project_scope_condition(detail_class, project_id))
                .order_by(
                    GraphApprovalRequest.column("created_at").desc(),
                    GraphApprovalRequest.column("id").desc(),
                )
                .limit(limit)
            )
            if status:
                query = query.where(GraphApprovalRequest.column("status") == status.value)
            if scope_table:
                query = query.where(detail_class.column("scope_table") == scope_table)
            if scope_id:
                query = query.where(detail_class.column("scope_id") == scope_id)
            with DbSession.use(readonly=True) as db:
                records.extend(db.exec(query).all())

        records.sort(key=lambda item: (item[0].created_at, item[0].id), reverse=True)
        return records[:limit]

    def count_pending_by_project(self, project_id: int) -> int:
        count = 0
        for detail_class in self.__get_model_classes():
            query = (
                SqlBuilder.select.count(GraphApprovalRequest, GraphApprovalRequest.column("id"))
                .join(
                    detail_class,
                    detail_class.column("approval_request_id") == GraphApprovalRequest.column("id"),
                )
                .where(GraphApprovalRequest.column("status") == GraphApprovalStatus.Pending.value)
                .where(self.__project_scope_condition(detail_class, project_id))
            )
            with DbSession.use(readonly=True) as db:
                count += db.exec(query).first() or 0
        return count

    def get_pending(self, origin_type: GraphApprovalOriginType | None = None) -> list[GraphApprovalRequest]:
        query = SqlBuilder.select.table(GraphApprovalRequest).where(
            GraphApprovalRequest.column("status") == GraphApprovalStatus.Pending.value
        )
        if origin_type:
            query = query.where(GraphApprovalRequest.column("request_type") == origin_type.value)
        with DbSession.use(readonly=True) as db:
            return db.exec(query).all()

    @staticmethod
    def __get_model_classes() -> list[type[BaseGraphApprovalRequestModel]]:
        return ModelHelper.get_models_by_base_class(BaseGraphApprovalRequestModel)

    @staticmethod
    def __project_scope_condition(detail_class: type[BaseGraphApprovalRequestModel], project_id: int) -> Any:
        scope_table = detail_class.column("scope_table")
        scope_id = detail_class.column("scope_id")
        return or_(
            and_(scope_table == Project.__tablename__, scope_id == project_id),
            and_(
                scope_table == ProjectColumn.__tablename__,
                scope_id.in_(
                    select(ProjectColumn.column("id")).where(ProjectColumn.column("project_id") == project_id)
                ),
            ),
            and_(
                scope_table == Card.__tablename__,
                scope_id.in_(select(Card.column("id")).where(Card.column("project_id") == project_id)),
            ),
            and_(
                scope_table == ProjectWiki.__tablename__,
                scope_id.in_(select(ProjectWiki.column("id")).where(ProjectWiki.column("project_id") == project_id)),
            ),
        )
