from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....domain.models import GraphApprovalRequest
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
                    SqlBuilder.select.table(detail_class).where(
                        detail_class.column("approval_request_id") == approval_id
                    )
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
        )
        with DbSession.use(readonly=True) as db:
            return db.exec(query).all()

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
