from typing import TypeVar
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TBaseParam, TUserParam
from ....domain.models import ChatSession
from ....domain.models.bases import BaseChatSessionModel
from ....helpers import InfraHelper


_TForeignSessionModel = TypeVar("_TForeignSessionModel", bound=BaseChatSessionModel)
TForeignSessionParam = _TForeignSessionModel | TBaseParam
TFilterableParam = BaseDbModel | TBaseParam


class ChatSessionRepository(BaseRepository[ChatSession]):
    @staticmethod
    def model_cls():
        return ChatSession

    @staticmethod
    def name() -> str:
        return "chat_session"

    def get_by_filterable(
        self, session_model: type[_TForeignSessionModel], session: TForeignSessionParam, filterable: TFilterableParam
    ) -> tuple[ChatSession, _TForeignSessionModel] | None:
        session_id = InfraHelper.convert_id(session)
        filterable_id = InfraHelper.convert_id(filterable)
        result = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(ChatSession, session_model)
                .join(
                    session_model,
                    ChatSession.column("id") == session_model.column("chat_session_id"),
                )
                .where(
                    (session_model.column(session_model.get_filterable_column()) == filterable_id)
                    & (session_model.column("id") == session_id)
                )
                .limit(1)
            )

            result = result.first()
        return result

    def get_all_by_user_and_filterable(
        self, user: TUserParam, session_model: type[_TForeignSessionModel], filterable: TFilterableParam
    ) -> list[tuple[ChatSession, _TForeignSessionModel]]:
        user_id = InfraHelper.convert_id(user)
        filterable_id = InfraHelper.convert_id(filterable)
        query = (
            SqlBuilder.select.tables(ChatSession, session_model)
            .join(
                session_model,
                ChatSession.column("id") == session_model.column("chat_session_id"),
            )
            .where(
                (ChatSession.column("user_id") == user_id)
                & (session_model.column(session_model.get_filterable_column()) == filterable_id)
            )
            .order_by(ChatSession.column("last_messaged_at").desc(), ChatSession.column("id").desc())
        )

        sessions = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            sessions = result.all()

        return sessions
