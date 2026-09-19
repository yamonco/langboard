from typing import Any, Literal, TypeVar
from ....core.db import BaseDbModel, ChatContentModel
from ....core.domain import BaseDomainService
from ....core.schema import TimeBasedPagination
from ....core.types.ParamTypes import TBaseParam, TChatHistoryParam, TChatSessionParam, TChatTemplateParam
from ....helpers import InfraHelper
from ...models import ChatHistory, ChatSession, ChatTemplate, User
from ...models.bases import BaseChatSessionModel


_TForeignSessionModel = TypeVar("_TForeignSessionModel", bound=BaseChatSessionModel)
TForeignSessionParam = BaseChatSessionModel | TBaseParam
TFilterableParam = BaseDbModel | TBaseParam


class ChatService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "chat"

    def get_session_by_id_like(self, session: TChatSessionParam | None) -> ChatSession | None:
        session = InfraHelper.get_by_id_like(ChatSession, session)
        return session

    def get_session_by_filterable(
        self,
        session_model: type[_TForeignSessionModel],
        session: TForeignSessionParam | None,
        filterable: TFilterableParam | None,
    ) -> tuple[ChatSession, _TForeignSessionModel] | None:
        if not session or not filterable:
            return None
        result = self.repo.chat_session.get_by_filterable(session_model, session, filterable)
        return result

    def get_api_session_list(
        self, user: User, session_model: type[_TForeignSessionModel], filterable: TFilterableParam
    ) -> list[dict[str, Any]]:
        if not filterable:
            return []

        sessions = self.repo.chat_session.get_all_by_user_and_filterable(user, session_model, filterable)

        chat_sessions = []
        for chat_session, session in sessions:
            chat_sessions.append({**chat_session.api_response(), **session.api_response()})

        return chat_sessions

    def ensure_session(
        self,
        user: User,
        session_model: type[_TForeignSessionModel],
        filterable: BaseDbModel,
        title: str = "",
    ) -> tuple[ChatSession, _TForeignSessionModel]:
        """Get or create the durable chat session bound to one filterable."""

        existing = self.get_session_by_filterable(session_model, None, filterable)
        if existing:
            return existing

        chat_session = ChatSession(user_id=user.id, title=title, last_messaged_at=None)
        self.repo.chat_session.insert(chat_session)

        bound_session = session_model(chat_session_id=chat_session.id)
        setattr(bound_session, session_model.get_filterable_column(), filterable.id)
        self.repo.chat_session.insert_bound_session(bound_session)
        return chat_session, bound_session

    def record_message(
        self,
        user: User,
        chat_session: TChatSessionParam | None,
        content: str,
        *,
        is_received: bool = False,
    ) -> ChatHistory | None:
        """Persist one history message and refresh session recency."""

        chat_session = InfraHelper.get_by_id_like(ChatSession, chat_session)
        if not chat_session or chat_session.user_id != user.id:
            return None

        chat_history = ChatHistory(
            chat_session_id=chat_session.id,
            message=ChatContentModel(content=content),
            is_received=is_received,
        )
        self.repo.chat_history.insert(chat_history)
        chat_session.last_messaged_at = chat_history.created_at
        self.repo.chat_session.update(chat_session)
        return chat_history

    def update_session(
        self, chat_session: TChatSessionParam | None, title: str | None = None, api_permission_level: str | None = None
    ):
        chat_session = InfraHelper.get_by_id_like(ChatSession, chat_session)
        if not chat_session:
            return None

        if title is not None:
            chat_session.title = title

        if api_permission_level is not None:
            chat_session.api_permission_level = api_permission_level

        self.repo.chat_session.update(chat_session)

        return chat_session

    def delete_session(self, chat_session: TChatSessionParam | None):
        chat_session = InfraHelper.get_by_id_like(ChatSession, chat_session)
        if not chat_session:
            return None

        self.repo.chat_session.delete(chat_session)

    def get_history_by_id_like(self, chat_history: TChatHistoryParam | None) -> ChatHistory | None:
        chat_history = InfraHelper.get_by_id_like(ChatHistory, chat_history)
        return chat_history

    def get_api_history_list(
        self,
        user: User,
        chat_session: TChatSessionParam | None,
        session_model: type[_TForeignSessionModel],
        session: TForeignSessionParam | None,
        pagination: TimeBasedPagination,
    ) -> list[dict[str, Any]]:
        result = InfraHelper.get_records_with_foreign_by_params((ChatSession, chat_session), (session_model, session))
        if not result:
            return []
        chat_session, session = result
        if chat_session.user_id != user.id:
            return []

        histories = self.repo.chat_history.get_all_by_user_scroller(user, chat_session, pagination)

        chat_histories = []
        session_uid = session.get_uid()
        for chat_history in histories:
            chat_histories.append({**chat_history.api_response(), "chat_session_uid": session_uid})

        return chat_histories

    def delete_history(self, chat_history: TChatHistoryParam | None):
        chat_history = InfraHelper.get_by_id_like(ChatHistory, chat_history)
        if not chat_history:
            return None

        self.repo.chat_history.delete(chat_history)

    def get_template_by_id_like(self, chat_template: TChatTemplateParam | None) -> ChatTemplate | None:
        chat_template = InfraHelper.get_by_id_like(ChatTemplate, chat_template)
        return chat_template

    def get_api_template_list(self, filterable_table: str, filterable_id: int | str) -> list[dict[str, Any]]:
        templates = self.repo.chat_template.get_all_by_filterable(filterable_table, filterable_id)

        return [template.api_response() for template in templates]

    def create_template(self, filterable: BaseDbModel, name: str, template: str) -> ChatTemplate:
        chat_template = ChatTemplate(
            filterable_table=filterable.__tablename__,
            filterable_id=filterable.id,
            name=name,
            template=template,
        )

        self.repo.chat_template.insert(chat_template)

        return chat_template

    def update_template(
        self, chat_template: TChatTemplateParam | None, name: str | None, template: str | None
    ) -> tuple[ChatTemplate, dict[str, Any]] | None | Literal[True]:
        chat_template = InfraHelper.get_by_id_like(ChatTemplate, chat_template)
        if not chat_template:
            return None

        model = {}
        if name:
            chat_template.name = name
            model["name"] = name

        if template:
            chat_template.template = template
            model["template"] = template

        if not model:
            return True

        self.repo.chat_template.update(chat_template)

        return chat_template, model

    def delete_template(self, chat_template: TChatTemplateParam | None) -> bool:
        chat_template = InfraHelper.get_by_id_like(ChatTemplate, chat_template)
        if not chat_template:
            return False

        self.repo.chat_template.delete(chat_template)
        return True
