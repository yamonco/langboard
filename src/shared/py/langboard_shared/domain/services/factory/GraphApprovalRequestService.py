from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from httpx import HTTPError, delete, post
from ....core.domain import BaseDomainService
from ....core.logger import Logger
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TProjectParam
from ....domain.models import (
    Bot,
    BotLog,
    Card,
    ChatHistory,
    ChatSession,
    GraphApprovalRequest,
    InternalBot,
    Project,
    ProjectColumn,
    ProjectWiki,
    User,
)
from ....domain.models.bases import BaseGraphApprovalBotRequest, BaseGraphApprovalRequestModel
from ....domain.models.BotLog import BotLogType
from ....domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from ....Env import Env
from ....helpers import InfraHelper
from ....publishers import GraphApprovalPublisher, ProjectBotPublisher


class GraphApprovalResumeError(Exception):
    pass


class GraphApprovalRequestService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "graph_approval_request"

    def get_api_list_by_project(
        self,
        project: TProjectParam,
        status: GraphApprovalStatus | None = None,
        origin_type: GraphApprovalOriginType | None = None,
        scope_table: str | None = None,
        scope_uid: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.expire_pending()
        project_id = InfraHelper.convert_id(project)
        scope_id = InfraHelper.convert_id(scope_uid) if scope_uid else None
        approvals = self.repo.graph_approval_request.get_ordered_by_project(
            project_id,
            status=status,
            origin_type=origin_type,
            scope_table=scope_table,
            scope_id=scope_id,
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for approval, detail in approvals:
            results.append(self.get_api_response(approval, detail))
            if len(results) >= limit:
                break
        return results

    def get_api_response(
        self, approval: GraphApprovalRequest, detail: BaseGraphApprovalRequestModel | None = None
    ) -> dict[str, Any]:
        response = approval.api_response()
        detail = detail or self.repo.graph_approval_request.get_detail(approval)
        if detail:
            detail_response = detail.api_response(is_graph_approval_request=True)
            for base_key in ("uid", "created_at", "updated_at", "approval_request_uid"):
                detail_response.pop(base_key, None)
            response.update(detail_response)

            project_id = self.__get_project_id(detail)
            if project_id:
                response["project_uid"] = project_id.to_short_code()

        return response

    def count_pending_by_project(self, project: TProjectParam) -> int:
        self.expire_pending()
        project_id = InfraHelper.convert_id(project)
        return self.repo.graph_approval_request.count_pending_by_project(project_id)

    def create_from_interrupt(
        self,
        project: Project,
        interrupt: dict[str, Any],
        *,
        user: User | None = None,
        bot: Bot | None = None,
        internal_bot: InternalBot | None = None,
        bot_log: BotLog | None = None,
        chat_session: ChatSession | None = None,
        chat_history: ChatHistory | None = None,
    ) -> GraphApprovalRequest | None:
        if interrupt.get("type") != "approval_request":
            return None

        origin_type = self.__parse_origin_type(interrupt.get("origin_type"))
        scope_table = self.__parse_scope_table(interrupt.get("scope_table"))
        if not origin_type or not scope_table:
            return None

        scope_uid = self.__string_or_none(interrupt.get("scope_uid"))
        scope_id = self.__parse_scope_id(project, scope_table, scope_uid)
        approval = GraphApprovalRequest(
            requested_by_user_id=user.id if user else None,
            thread_id=str(interrupt.get("thread_id") or ""),
            run_id=str(interrupt.get("run_id") or ""),
            request_type=origin_type,
            action_type=str(interrupt.get("action_type") or "api_call"),
            permission=str(interrupt.get("permission") or ""),
            tool_name=self.__string_or_none(interrupt.get("tool_name")),
            api_name=self.__string_or_none(interrupt.get("api_name")),
            request_payload=self.__dict_or_empty(interrupt.get("request_payload")),
            preview_payload=self.__dict_or_empty(interrupt.get("preview")),
            status=GraphApprovalStatus.Pending,
            expires_at=self.__parse_expires_at(interrupt.get("expires_at")),
        )
        if not self.__scope_exists(project, scope_table, scope_id):
            self.__cancel_unpersisted(approval, project, "scope deleted", bot_log=bot_log)
            return None

        document_name = self.__string_or_none(interrupt.get("document_name"))
        if not self.__is_valid_detail_origin(origin_type, chat_session, chat_history, document_name):
            self.__cancel_unpersisted(approval, project, "invalid approval origin detail", bot_log=bot_log)
            return None

        detail = self.__create_detail(
            approval,
            origin_type,
            scope_table,
            scope_id,
            bot=bot,
            internal_bot=internal_bot,
            bot_log=bot_log,
            chat_session=chat_session,
            chat_history=chat_history,
            document_name=document_name,
        )
        self.repo.graph_approval_request.insert_with_detail(approval, detail)
        return approval

    def approve(
        self, approval_uid: str, user: User, project: TProjectParam | None = None
    ) -> GraphApprovalRequest | None:
        approval = self.repo.graph_approval_request.get_by_id_like(approval_uid)
        if project and approval and self.__get_project_id(approval) != InfraHelper.convert_id(project):
            return None
        if not approval or approval.status != GraphApprovalStatus.Pending:
            return None
        project_obj = project if isinstance(project, Project) else self.__get_project(approval)
        if self.__expire_if_needed(approval, project_obj):
            return None

        resume_result = self.__resume_graph(approval, {"approved": True, "rejected": False})
        approval.status = GraphApprovalStatus.Approved
        approval.resolved_by_user_id = user.id
        approval.resolved_at = SafeDateTime.now()
        approval.rejection_reason = None
        self.repo.graph_approval_request.update(approval)
        self.__append_bot_log(
            approval,
            f"Graph approval approved by {user.email}",
            project=project_obj,
        )
        self.__append_bot_log(
            approval,
            self.__get_resume_log_message(resume_result, "Graph resumed after approval"),
            log_type=BotLogType.Success,
            project=project_obj,
        )
        self.__acknowledge_graph(approval, resume_result)
        return approval

    def reject(
        self, approval_uid: str, user: User, reason: str | None = None, project: TProjectParam | None = None
    ) -> GraphApprovalRequest | None:
        approval = self.repo.graph_approval_request.get_by_id_like(approval_uid)
        if project and approval and self.__get_project_id(approval) != InfraHelper.convert_id(project):
            return None
        if not approval or approval.status != GraphApprovalStatus.Pending:
            return None
        project_obj = project if isinstance(project, Project) else self.__get_project(approval)
        if self.__expire_if_needed(approval, project_obj):
            return None

        resume_result = self.__resume_graph(approval, {"approved": False, "rejected": True, "reason": reason or ""})
        approval.status = GraphApprovalStatus.Rejected
        approval.resolved_by_user_id = user.id
        approval.resolved_at = SafeDateTime.now()
        approval.rejection_reason = reason
        self.repo.graph_approval_request.update(approval)
        self.__append_bot_log(
            approval,
            f"Graph approval rejected by {user.email}",
            project=project_obj,
        )
        self.__append_bot_log(
            approval,
            self.__get_resume_log_message(resume_result, "Graph resumed after rejection"),
            log_type=BotLogType.Info,
            project=project_obj,
        )
        self.__acknowledge_graph(approval, resume_result)
        return approval

    def expire_pending(self) -> list[GraphApprovalRequest]:
        expired_approvals = self.repo.graph_approval_request.get_expired_pending()
        for approval in expired_approvals:
            project = self.__get_project(approval)
            self.__expire(approval, project)
        return expired_approvals

    def cancel_pending_by_scope(
        self,
        project: Project,
        scope_table: str,
        scope_uid: str,
        *,
        reason: str,
        origin_type: GraphApprovalOriginType | None = None,
        bot: Bot | None = None,
    ) -> list[GraphApprovalRequest]:
        project_id = InfraHelper.convert_id(project)
        scope_id = InfraHelper.convert_id(scope_uid)
        approvals = [
            approval
            for approval in self.repo.graph_approval_request.get_pending(origin_type)
            if self.__matches_scope(approval, project_id, scope_table, scope_id, bot_id=bot.id if bot else None)
        ]
        for approval in approvals:
            self.__cancel(approval, project, reason)
        return approvals

    def cancel_pending_by_bot(self, bot: Bot, *, reason: str) -> list[GraphApprovalRequest]:
        approvals = [
            approval
            for approval in self.repo.graph_approval_request.get_pending()
            if (detail := self.repo.graph_approval_request.get_detail(approval))
            and isinstance(detail, BaseGraphApprovalBotRequest)
            and detail.bot_id == bot.id
        ]
        for approval in approvals:
            self.__cancel(approval, self.__get_project(approval), reason)
        return approvals

    def cancel_pending_by_internal_bot(self, internal_bot: InternalBot, *, reason: str) -> list[GraphApprovalRequest]:
        approvals = [
            approval
            for approval in self.repo.graph_approval_request.get_pending()
            if (detail := self.repo.graph_approval_request.get_detail(approval))
            and isinstance(detail, BaseGraphApprovalBotRequest)
            and detail.internal_bot_id == internal_bot.id
        ]
        for approval in approvals:
            self.__cancel(approval, self.__get_project(approval), reason)
        return approvals

    @staticmethod
    def __parse_origin_type(value: Any) -> GraphApprovalOriginType | None:
        if isinstance(value, GraphApprovalOriginType):
            return value
        if isinstance(value, str):
            for origin_type in GraphApprovalOriginType:
                if origin_type.value == value:
                    return origin_type
        return None

    @staticmethod
    def __parse_scope_table(value: Any) -> str | None:
        if isinstance(value, str) and value in {
            Project.__tablename__,
            ProjectColumn.__tablename__,
            Card.__tablename__,
            ProjectWiki.__tablename__,
        }:
            return value
        return None

    @staticmethod
    def __string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        value = str(value)
        return value or None

    @staticmethod
    def __dict_or_empty(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def __parse_scope_id(project: Project, scope_table: str, scope_uid: str | None) -> SnowflakeID | None:
        if scope_table == Project.__tablename__ and not scope_uid:
            return project.id
        if not scope_uid:
            return None
        return InfraHelper.convert_id(scope_uid)

    def __scope_exists(self, project: Project, scope_table: str, scope_id: SnowflakeID | None) -> bool:
        if scope_table == Project.__tablename__:
            if not scope_id:
                return False
            target_project = self.repo.project.get_by_id_like(scope_id)
            return bool(target_project and target_project.id == project.id)

        if not scope_id:
            return False

        if scope_table == ProjectColumn.__tablename__:
            target_column = self.repo.project_column.get_by_id_like(scope_id)
            return bool(target_column and target_column.project_id == project.id)

        if scope_table == Card.__tablename__:
            target_card = self.repo.card.get_by_id_like(scope_id)
            return bool(target_card and target_card.project_id == project.id)

        if scope_table == ProjectWiki.__tablename__:
            target_wiki = self.repo.project_wiki.get_by_id_like(scope_id)
            return bool(target_wiki and target_wiki.project_id == project.id)

        return False

    def __create_detail(
        self,
        approval: GraphApprovalRequest,
        origin_type: GraphApprovalOriginType,
        scope_table: str,
        scope_id: SnowflakeID | None,
        *,
        bot: Bot | None,
        internal_bot: InternalBot | None,
        bot_log: BotLog | None,
        chat_session: ChatSession | None,
        chat_history: ChatHistory | None,
        document_name: str | None,
    ) -> BaseGraphApprovalRequestModel:
        detail_class = self.repo.graph_approval_request.get_model_class(origin_type)
        if not detail_class:
            raise ValueError(f"Unsupported graph approval origin type: {origin_type}")

        return detail_class.create_for_approval(
            approval,
            scope_table,
            scope_id,
            bot=bot,
            internal_bot=internal_bot,
            bot_log=bot_log,
            chat_session=chat_session,
            chat_history=chat_history,
            document_name=document_name,
        )

    @staticmethod
    def __is_valid_detail_origin(
        origin_type: GraphApprovalOriginType,
        chat_session: ChatSession | None,
        chat_history: ChatHistory | None,
        document_name: str | None,
    ) -> bool:
        if origin_type == GraphApprovalOriginType.Chat:
            return bool(chat_session and chat_history)
        if origin_type == GraphApprovalOriginType.Editor:
            return bool(document_name)
        return origin_type in (
            GraphApprovalOriginType.Trigger,
            GraphApprovalOriginType.Schedule,
            GraphApprovalOriginType.ManualScopeRun,
        )

    @staticmethod
    def __parse_expires_at(value: SafeDateTime | datetime | str | None) -> SafeDateTime | None:
        if isinstance(value, datetime):
            return GraphApprovalRequestService.__to_safe_datetime(value)
        if not value:
            return None
        try:
            expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return GraphApprovalRequestService.__to_safe_datetime(expires_at)
        except ValueError:
            return None

    @staticmethod
    def __to_safe_datetime(value: datetime) -> SafeDateTime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return SafeDateTime.fromtimestamp(value.timestamp(), timezone.utc)

    def __expire_if_needed(self, approval: GraphApprovalRequest, project: Project | None) -> bool:
        expires_at = self.__parse_expires_at(approval.expires_at)
        if expires_at is None or expires_at > SafeDateTime.now():
            return False
        self.__expire(approval, project)
        return True

    def __expire(self, approval: GraphApprovalRequest, project: Project | None) -> None:
        self.__resolve_without_user(
            approval,
            GraphApprovalStatus.Expired,
            "Graph approval expired",
            "Graph resumed after approval expiry",
            {"approved": False, "rejected": True, "expired": True, "reason": "Approval expired"},
            project,
        )

    def __cancel(self, approval: GraphApprovalRequest, project: Project | None, reason: str) -> None:
        self.__resolve_without_user(
            approval,
            GraphApprovalStatus.Cancelled,
            f"Graph approval cancelled: {reason}",
            "Graph resumed after approval cancellation",
            {"approved": False, "rejected": True, "cancelled": True, "reason": reason},
            project,
        )

    def __cancel_unpersisted(
        self, approval: GraphApprovalRequest, project: Project, reason: str, *, bot_log: BotLog | None = None
    ) -> None:
        try:
            resume_result = self.__resume_graph(
                approval,
                {"approved": False, "rejected": True, "cancelled": True, "reason": reason},
            )
            resume_message = self.__get_resume_log_message(resume_result, "Graph resumed after approval cancellation")
            self.__acknowledge_graph(approval, resume_result)
        except GraphApprovalResumeError as error:
            resume_message = f"Graph resumed after approval cancellation failed: {error}"

        if bot_log:
            self.__append_bot_log_record(bot_log, f"Graph approval cancelled: {reason}", project=project)
            self.__append_bot_log_record(bot_log, resume_message, project=project)

    def __resolve_without_user(
        self,
        approval: GraphApprovalRequest,
        status: GraphApprovalStatus,
        status_message: str,
        resume_fallback: str,
        resume: dict[str, Any],
        project: Project | None,
    ) -> None:
        if approval.status != GraphApprovalStatus.Pending:
            return

        resume_result: dict[str, Any] | None = None
        try:
            resume_result = self.__resume_graph(approval, resume)
            resume_message = self.__get_resume_log_message(resume_result, resume_fallback)
        except GraphApprovalResumeError as error:
            resume_message = f"{resume_fallback} failed: {error}"

        approval.status = status
        approval.resolved_at = SafeDateTime.now()
        self.repo.graph_approval_request.update(approval)
        self.__append_bot_log(approval, status_message, project=project)
        self.__append_bot_log(approval, resume_message, project=project)
        if project:
            GraphApprovalPublisher.updated(project, self.get_api_response(approval))
        if resume_result is not None:
            self.__acknowledge_graph(approval, resume_result)

    def __get_project(self, approval: GraphApprovalRequest) -> Project | None:
        project_id = self.__get_project_id(approval)
        if not project_id:
            return None
        return self.repo.project.get_by_id_like(project_id)

    def __get_project_id(self, approval: GraphApprovalRequest | BaseGraphApprovalRequestModel) -> SnowflakeID | None:
        detail = (
            approval
            if isinstance(approval, BaseGraphApprovalRequestModel)
            else self.repo.graph_approval_request.get_detail(approval)
        )
        if not detail or not detail.scope_id:
            return None

        if detail.scope_table == Project.__tablename__:
            return detail.scope_id if self.repo.project.get_by_id_like(detail.scope_id) else None

        if detail.scope_table == ProjectColumn.__tablename__:
            column = self.repo.project_column.get_by_id_like(detail.scope_id)
            return column.project_id if column else None

        if detail.scope_table == Card.__tablename__:
            card = self.repo.card.get_by_id_like(detail.scope_id)
            return card.project_id if card else None

        if detail.scope_table == ProjectWiki.__tablename__:
            wiki = self.repo.project_wiki.get_by_id_like(detail.scope_id)
            return wiki.project_id if wiki else None

        return None

    def __matches_scope(
        self,
        approval: GraphApprovalRequest,
        project_id: SnowflakeID,
        scope_table: str,
        scope_id: SnowflakeID,
        *,
        bot_id: SnowflakeID | None = None,
    ) -> bool:
        detail = self.repo.graph_approval_request.get_detail(approval)
        if not detail or self.__get_project_id(detail) != project_id:
            return False
        if detail.scope_table != scope_table or detail.scope_id != scope_id:
            return False
        if bot_id and (not isinstance(detail, BaseGraphApprovalBotRequest) or detail.bot_id != bot_id):
            return False
        return True

    def __append_bot_log(
        self,
        approval: GraphApprovalRequest,
        message: str,
        *,
        log_type: BotLogType = BotLogType.Info,
        project: Project | None = None,
    ) -> None:
        detail = self.repo.graph_approval_request.get_detail(approval)
        if not isinstance(detail, BaseGraphApprovalBotRequest) or not detail.bot_log_id:
            return

        bot_log = self.repo.bot_log.get_by_id_like(detail.bot_log_id)
        if not bot_log:
            return

        self.__append_bot_log_record(bot_log, message, log_type=log_type, project=project)

    def __append_bot_log_record(
        self, bot_log: BotLog, message: str, *, log_type: BotLogType = BotLogType.Info, project: Project | None = None
    ) -> None:
        bot_log.log_type = log_type
        log_stack = bot_log.append_message(message, log_type)
        self.repo.bot_log.update(bot_log)

        if project:
            ProjectBotPublisher.log_stack_added(project, bot_log, log_stack)

    @staticmethod
    def __get_resume_log_message(resume_result: dict[str, Any], fallback: str) -> str:
        message = resume_result.get("message")
        if isinstance(message, str) and message:
            return message
        return fallback

    @staticmethod
    def __resume_graph(approval: GraphApprovalRequest, resume: dict[str, Any]) -> dict[str, Any]:
        if not approval.thread_id:
            raise GraphApprovalResumeError("Graph approval request has no thread ID.")

        try:
            response = post(
                f"{Env.DEFAULT_GRAPH_URL}/api/v1/graph/resume/{quote(approval.thread_id, safe='')}",
                json={
                    "resume": resume,
                    "session_id": approval.thread_id,
                },
                timeout=Env.AI_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        except HTTPError as error:
            raise GraphApprovalResumeError(str(error)) from error

    @staticmethod
    def __acknowledge_graph(approval: GraphApprovalRequest, resume_result: dict[str, Any]) -> None:
        if not approval.thread_id or resume_result.get("interrupts"):
            return

        try:
            response = delete(
                f"{Env.DEFAULT_GRAPH_URL}/api/v1/graph/status/{quote(approval.thread_id, safe='')}",
                timeout=Env.AI_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except HTTPError as error:
            Logger.main.warning("Failed to clean completed graph checkpoint: %s", error)
