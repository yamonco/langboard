from collections.abc import Mapping
from datetime import timedelta, timezone
from typing import Any, NamedTuple
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from ....core.db import ChatContentModel, DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....domain.models import (
    ChatGraphApprovalRequest,
    ChatHistory,
    ChatSession,
    EditorGraphApprovalRequest,
    GraphApprovalRequest,
    InternalBotRun,
    ProjectChatSession,
)
from ....domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from ....domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus


class BoardChatResumeResult(NamedTuple):
    run: InternalBotRun
    original_message: ChatHistory
    resumed_message: ChatHistory | None
    resolved_approval: GraphApprovalRequest | None
    requested_approval: GraphApprovalRequest | None
    newly_applied: bool


class EditorResumeResult(NamedTuple):
    run: InternalBotRun
    resolved_approval: GraphApprovalRequest | None
    requested_approval: GraphApprovalRequest | None
    newly_applied: bool


class EditorResumeFailure(NamedTuple):
    run: InternalBotRun
    expired_approval: GraphApprovalRequest | None
    newly_applied: bool


class InternalBotRunRepository(BaseRepository[InternalBotRun]):
    @staticmethod
    def model_cls() -> type[InternalBotRun]:
        return InternalBotRun

    @staticmethod
    def name() -> str:
        return "internal_bot_run"

    def accept(self, candidate: InternalBotRun) -> tuple[InternalBotRun, bool]:
        for _ in range(2):
            try:
                with DbSession.use(readonly=False) as db:
                    return self._accept_in_transaction(db, candidate)
            except IntegrityError:
                continue
        raise RuntimeError("Could not accept a concurrent internal bot run")

    def accept_board_chat(
        self,
        candidate: InternalBotRun,
        message: str,
        permission_level: str,
        project_chat_session_id: SnowflakeID | None,
    ) -> tuple[InternalBotRun, bool, ChatSession, ProjectChatSession, ChatHistory]:
        for _ in range(2):
            try:
                with DbSession.use(readonly=False) as db:
                    run, accepted = self._accept_in_transaction(db, candidate)
                    if run.chat_history_id is None:
                        if run.status != InternalBotRunStatus.Accepted:
                            raise RuntimeError("An active AI run is missing its chat message")
                        chat_session = self._get_or_create_chat_session(
                            db, run, permission_level, project_chat_session_id
                        )
                        user_message = ChatHistory(
                            chat_session_id=chat_session.id,
                            message=ChatContentModel(content=message),
                            is_received=False,
                        )
                        db.insert(user_message)
                        chat_session.last_messaged_at = user_message.created_at
                        db.update(chat_session)
                        run.chat_session_id = chat_session.id
                        run.chat_history_id = user_message.id
                        db.update(run)
                        accepted = True
                    else:
                        chat_session = db.exec(
                            SqlBuilder.select.table(ChatSession).where(ChatSession.column("id") == run.chat_session_id)
                        ).first()
                        user_message = db.exec(
                            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == run.chat_history_id)
                        ).first()
                        if chat_session is None or user_message is None:
                            raise RuntimeError("An accepted AI run has missing chat records")

                    project_session = db.exec(
                        SqlBuilder.select.table(ProjectChatSession).where(
                            (ProjectChatSession.column("project_id") == run.project_id)
                            & (ProjectChatSession.column("chat_session_id") == chat_session.id)
                        )
                    ).first()
                    if project_session is None:
                        raise RuntimeError("An accepted AI run has no project chat session")
                    if project_chat_session_id is not None and project_session.id != project_chat_session_id:
                        raise ValueError("A different chat session already uses this task identity")
                    return run, accepted, chat_session, project_session, user_message
            except IntegrityError:
                continue
        raise RuntimeError("Could not accept a concurrent board chat run")

    def _get_or_create_chat_session(
        self, db: DbSession, run: InternalBotRun, permission_level: str, project_chat_session_id: SnowflakeID | None
    ) -> ChatSession:
        if run.chat_session_id is None and project_chat_session_id is None:
            chat_session = ChatSession(
                user_id=run.user_id,
                title="Untitled",
                api_permission_level=permission_level,
                last_messaged_at=SafeDateTime.now(),
            )
            db.insert(chat_session)
            db.insert(ProjectChatSession(chat_session_id=chat_session.id, project_id=run.project_id))
            return chat_session

        project_session = None
        if project_chat_session_id is not None:
            project_session = db.exec(
                SqlBuilder.select.table(ProjectChatSession).where(
                    (ProjectChatSession.column("id") == project_chat_session_id)
                    & (ProjectChatSession.column("project_id") == run.project_id)
                )
            ).first()
            if project_session is None:
                raise PermissionError("Chat session is not assigned to this project")
            if run.chat_session_id is not None and run.chat_session_id != project_session.chat_session_id:
                raise ValueError("A different chat session already uses this task identity")

        session_id = project_session.chat_session_id if project_session else run.chat_session_id
        chat_session = db.exec(
            SqlBuilder.select.table(ChatSession)
            .where((ChatSession.column("id") == session_id) & (ChatSession.column("user_id") == run.user_id))
            .with_for_update()
        ).first()
        if project_session is None:
            project_session = db.exec(
                SqlBuilder.select.table(ProjectChatSession).where(
                    (ProjectChatSession.column("project_id") == run.project_id)
                    & (ProjectChatSession.column("chat_session_id") == session_id)
                )
            ).first()
        if chat_session is None or project_session is None:
            raise PermissionError("Chat session is not assigned to this user and project")
        chat_session.api_permission_level = permission_level
        return chat_session

    def _accept_in_transaction(self, db: DbSession, candidate: InternalBotRun) -> tuple[InternalBotRun, bool]:
        is_postgresql = DbEngine.get_main_engine().dialect.name == "postgresql"
        if is_postgresql:
            candidate.id = SnowflakeID()
            db.exec(
                pg_insert(InternalBotRun)
                .values(
                    id=candidate.id,
                    created_at=candidate.created_at,
                    updated_at=candidate.created_at,
                    request_key=candidate.request_key,
                    request_digest=candidate.request_digest,
                    client_task_id=candidate.client_task_id,
                    user_id=candidate.user_id,
                    project_id=candidate.project_id,
                    internal_bot_id=candidate.internal_bot_id,
                    chat_session_id=candidate.chat_session_id,
                    chat_history_id=candidate.chat_history_id,
                    ai_chat_history_id=candidate.ai_chat_history_id,
                    kind=candidate.kind,
                    status=candidate.status,
                    scope_table=candidate.scope_table,
                    scope_uid=candidate.scope_uid,
                    graph_session_id=candidate.graph_session_id,
                    graph_thread_id=candidate.graph_thread_id,
                    request_payload=candidate.request_payload,
                    output_text=candidate.output_text,
                    attempt=candidate.attempt,
                    lease_expires_at=candidate.lease_expires_at,
                    finished_at=candidate.finished_at,
                    error_message=candidate.error_message,
                )
                .on_conflict_do_nothing(index_elements=[InternalBotRun.column("request_key")])
            )

        existing = db.exec(
            SqlBuilder.select.table(InternalBotRun)
            .where(InternalBotRun.column("request_key") == candidate.request_key)
            .with_for_update()
        ).first()
        if existing is None:
            db.insert(candidate)
            return candidate, True
        if existing.request_digest != candidate.request_digest:
            raise ValueError("A different AI request already uses this task identity")
        return existing, is_postgresql and existing.id == candidate.id

    def claim(self, run_id: SnowflakeID, lease_seconds: int) -> InternalBotRun | None:
        if lease_seconds <= 0:
            raise ValueError("The AI run lease must be positive")
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun).where(InternalBotRun.column("id") == run_id).with_for_update()
            ).first()
            if run is None or run.status != InternalBotRunStatus.Accepted:
                return None

            now = SafeDateTime.now()
            run.status = InternalBotRunStatus.Streaming
            run.attempt += 1
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            db.update(run)
            return run

    def get_board_chat_context(
        self, run_id: SnowflakeID
    ) -> tuple[InternalBotRun, ProjectChatSession, ChatHistory] | None:
        with DbSession.use(readonly=False) as db:
            run = db.exec(SqlBuilder.select.table(InternalBotRun).where(InternalBotRun.column("id") == run_id)).first()
            if (
                run is None
                or run.kind != InternalBotRunKind.BoardChat
                or run.chat_session_id is None
                or run.chat_history_id is None
            ):
                return None

            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession).where(
                    (ChatSession.column("id") == run.chat_session_id) & (ChatSession.column("user_id") == run.user_id)
                )
            ).first()
            project_session = db.exec(
                SqlBuilder.select.table(ProjectChatSession).where(
                    (ProjectChatSession.column("project_id") == run.project_id)
                    & (ProjectChatSession.column("chat_session_id") == run.chat_session_id)
                )
            ).first()
            user_message = db.exec(
                SqlBuilder.select.table(ChatHistory).where(
                    (ChatHistory.column("id") == run.chat_history_id)
                    & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    & ChatHistory.column("is_received").is_(False)
                )
            ).first()
            if chat_session is None or project_session is None or user_message is None:
                return None
            return run, project_session, user_message

    def get_board_chat_run(self, run_id: SnowflakeID) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
            ).first()

    def list_accepted_board_chat_runs(self, limit: int, after_id: SnowflakeID | None = None) -> list[InternalBotRun]:
        if limit <= 0:
            return []
        with DbSession.use(readonly=False) as db:
            statement = SqlBuilder.select.table(InternalBotRun).where(
                (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                & (InternalBotRun.column("status") == InternalBotRunStatus.Accepted)
            )
            if after_id is not None:
                statement = statement.where(InternalBotRun.column("id") > after_id)
            return db.exec(statement.order_by(InternalBotRun.column("id")).limit(limit)).all()

    def list_accepted_editor_runs(self, limit: int, after_id: SnowflakeID | None = None) -> list[InternalBotRun]:
        if limit <= 0:
            return []
        with DbSession.use(readonly=False) as db:
            statement = SqlBuilder.select.table(InternalBotRun).where(
                InternalBotRun.column("kind").in_((InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot))
                & (InternalBotRun.column("status") == InternalBotRunStatus.Accepted)
            )
            if after_id is not None:
                statement = statement.where(InternalBotRun.column("id") > after_id)
            return db.exec(statement.order_by(InternalBotRun.column("id")).limit(limit)).all()

    def get_owned_board_chat_status(
        self, request_key: str, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> tuple[InternalBotRun, ProjectChatSession, ChatHistory, ChatHistory | None] | None:
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("request_key") == request_key)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
            ).first()
            if run is None or run.chat_session_id is None or run.chat_history_id is None:
                return None

            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession).where(
                    (ChatSession.column("id") == run.chat_session_id) & (ChatSession.column("user_id") == user_id)
                )
            ).first()
            project_session = db.exec(
                SqlBuilder.select.table(ProjectChatSession).where(
                    (ProjectChatSession.column("project_id") == project_id)
                    & (ProjectChatSession.column("chat_session_id") == run.chat_session_id)
                )
            ).first()
            user_message = db.exec(
                SqlBuilder.select.table(ChatHistory).where(
                    (ChatHistory.column("id") == run.chat_history_id)
                    & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    & ChatHistory.column("is_received").is_(False)
                )
            ).first()
            if chat_session is None or project_session is None or user_message is None:
                return None

            ai_message = None
            if run.ai_chat_history_id is not None:
                ai_message = db.exec(
                    SqlBuilder.select.table(ChatHistory).where(
                        (ChatHistory.column("id") == run.ai_chat_history_id)
                        & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                        & ChatHistory.column("is_received").is_(True)
                    )
                ).first()
            return run, project_session, user_message, ai_message

    def get_editor_run_by_request_key(
        self, request_key: str, user_id: SnowflakeID, project_id: SnowflakeID, kind: InternalBotRunKind
    ) -> InternalBotRun | None:
        if kind not in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot):
            raise ValueError("Only editor AI runs can be cancelled here")
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("request_key") == request_key)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("kind") == kind)
                )
            ).first()

    def cancel_board_chat(
        self, request_key: str, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("request_key") == request_key)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
                .with_for_update()
            ).first()
            if run is None:
                return None
            if run.status == InternalBotRunStatus.Cancelled:
                return run
            if run.status not in (InternalBotRunStatus.Accepted, InternalBotRunStatus.Streaming):
                return None

            if run.ai_chat_history_id is not None:
                ai_message = db.exec(
                    SqlBuilder.select.table(ChatHistory)
                    .where(
                        (ChatHistory.column("id") == run.ai_chat_history_id)
                        & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                        & ChatHistory.column("is_received").is_(True)
                    )
                    .with_for_update()
                ).first()
                if ai_message is None:
                    raise RuntimeError("The AI run has no bound response message")
                if ai_message.message.content:
                    run.output_text = ai_message.message.content
                else:
                    db.delete(ai_message)

            run.status = InternalBotRunStatus.Cancelled
            run.lease_expires_at = None
            run.finished_at = SafeDateTime.now()
            db.update(run)
            return run

    def cancel_editor(
        self, request_key: str, user_id: SnowflakeID, project_id: SnowflakeID, kind: InternalBotRunKind
    ) -> InternalBotRun | None:
        if kind not in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot):
            raise ValueError("Only editor AI runs can be cancelled here")
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("request_key") == request_key)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("kind") == kind)
                )
                .with_for_update()
            ).first()
            if run is None:
                return None
            if run.status == InternalBotRunStatus.Cancelled:
                return run
            if run.status not in (InternalBotRunStatus.Accepted, InternalBotRunStatus.Streaming):
                return None
            run.status = InternalBotRunStatus.Cancelled
            run.lease_expires_at = None
            run.finished_at = SafeDateTime.now()
            db.update(run)
            return run

    def get_board_chat_run_by_ai_message(
        self, project_id: SnowflakeID, user_id: SnowflakeID, ai_message_id: SnowflakeID
    ) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("ai_chat_history_id") == ai_message_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
            ).first()

    def get_board_chat_run_by_approval(self, approval_id: SnowflakeID) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval_id)
            ).first()
            detail = db.exec(
                SqlBuilder.select.table(ChatGraphApprovalRequest).where(
                    ChatGraphApprovalRequest.column("approval_request_id") == approval_id
                )
            ).first()
            if approval is None or detail is None or approval.requested_by_user_id is None:
                return None
            return db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("client_task_id") == approval.run_id)
                    & (InternalBotRun.column("chat_session_id") == detail.chat_session_id)
                    & (InternalBotRun.column("graph_thread_id") == approval.thread_id)
                    & (InternalBotRun.column("user_id") == approval.requested_by_user_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
            ).first()

    def get_editor_run_by_approval(self, approval_id: SnowflakeID) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval_id)
            ).first()
            detail = db.exec(
                SqlBuilder.select.table(EditorGraphApprovalRequest).where(
                    EditorGraphApprovalRequest.column("approval_request_id") == approval_id
                )
            ).first()
            if approval is None or detail is None or approval.requested_by_user_id is None or detail.scope_id is None:
                return None
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun).where(
                    (InternalBotRun.column("graph_thread_id") == approval.thread_id)
                    & (InternalBotRun.column("user_id") == approval.requested_by_user_id)
                    & (InternalBotRun.column("scope_table") == detail.scope_table)
                    & (InternalBotRun.column("scope_uid") == detail.scope_id.to_short_code())
                    & InternalBotRun.column("kind").in_(
                        (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                    )
                )
            ).first()
            if run is None or run.request_payload.get("document_name") != detail.document_name:
                return None
            interrupt = run.request_payload.get("graph_interrupt")
            value = interrupt.get("value", interrupt) if isinstance(interrupt, dict) else None
            return run if isinstance(value, dict) and value.get("approval_uid") == approval.get_uid() else None

    def close_editor_approval(
        self, approval_id: SnowflakeID, status: GraphApprovalStatus, reason: str
    ) -> GraphApprovalRequest | None:
        if status not in (GraphApprovalStatus.Expired, GraphApprovalStatus.Cancelled):
            raise ValueError("An editor approval can only be expired or cancelled here")
        with DbSession.use(readonly=False) as db:
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest)
                .where(GraphApprovalRequest.column("id") == approval_id)
                .with_for_update()
            ).first()
            detail = db.exec(
                SqlBuilder.select.table(EditorGraphApprovalRequest).where(
                    EditorGraphApprovalRequest.column("approval_request_id") == approval_id
                )
            ).first()
            if (
                approval is None
                or detail is None
                or approval.request_type != GraphApprovalOriginType.Editor
                or approval.status != GraphApprovalStatus.Pending
                or approval.requested_by_user_id is None
                or detail.scope_id is None
            ):
                return None
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("graph_thread_id") == approval.thread_id)
                    & (InternalBotRun.column("user_id") == approval.requested_by_user_id)
                    & (InternalBotRun.column("scope_table") == detail.scope_table)
                    & (InternalBotRun.column("scope_uid") == detail.scope_id.to_short_code())
                    & (InternalBotRun.column("status") == InternalBotRunStatus.AwaitingApproval)
                    & InternalBotRun.column("kind").in_(
                        (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                    )
                )
                .with_for_update()
            ).first()
            if run is None or run.request_payload.get("document_name") != detail.document_name:
                return None
            interrupt = run.request_payload.get("graph_interrupt")
            if not isinstance(interrupt, dict):
                return None
            value = interrupt.get("value", interrupt)
            if not isinstance(value, dict) or value.get("approval_uid") != approval.get_uid():
                return None

            now = SafeDateTime.now()
            approval.status = status
            approval.resolved_at = now
            db.update(approval)
            resolved_value = {
                **value,
                "status": status.value,
                "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            saved_interrupt = {**interrupt, "value": resolved_value} if "value" in interrupt else resolved_value
            run.request_payload = {**run.request_payload, "graph_interrupt": saved_interrupt}
            run.status = (
                InternalBotRunStatus.Failed if status == GraphApprovalStatus.Expired else InternalBotRunStatus.Cancelled
            )
            run.error_message = reason[:1000]
            run.lease_expires_at = None
            run.finished_at = now
            db.update(run)
            return approval

    def claim_editor_resume(
        self,
        approval_id: SnowflakeID,
        project_id: SnowflakeID,
        approver_id: SnowflakeID,
        decision: Mapping[str, bool | str],
        lease_seconds: int,
    ) -> InternalBotRun | None:
        if lease_seconds <= 0:
            raise ValueError("The AI run lease must be positive")
        approved = decision.get("approved") is True
        rejected = decision.get("rejected") is True
        reason = decision.get("reason")
        if (
            set(decision) - {"approved", "rejected", "reason"}
            or type(decision.get("approved")) is not bool
            or type(decision.get("rejected")) is not bool
            or approved == rejected
            or (reason is not None and (not rejected or not isinstance(reason, str) or len(reason) > 1000))
        ):
            raise ValueError("Exactly one editor approval decision is required")

        with DbSession.use(readonly=False) as db:
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest)
                .where(GraphApprovalRequest.column("id") == approval_id)
                .with_for_update()
            ).first()
            detail = db.exec(
                SqlBuilder.select.table(EditorGraphApprovalRequest).where(
                    EditorGraphApprovalRequest.column("approval_request_id") == approval_id
                )
            ).first()
            if (
                approval is None
                or detail is None
                or approval.request_type != GraphApprovalOriginType.Editor
                or approval.status != GraphApprovalStatus.Pending
                or approval.requested_by_user_id is None
                or detail.scope_id is None
                or self._approval_expired(approval)
            ):
                return None
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("user_id") == approval.requested_by_user_id)
                    & (InternalBotRun.column("graph_thread_id") == approval.thread_id)
                    & (InternalBotRun.column("scope_table") == detail.scope_table)
                    & (InternalBotRun.column("scope_uid") == detail.scope_id.to_short_code())
                    & (InternalBotRun.column("status") == InternalBotRunStatus.AwaitingApproval)
                    & InternalBotRun.column("kind").in_(
                        (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                    )
                )
                .with_for_update()
            ).first()
            if (
                run is None
                or not run.graph_session_id
                or run.request_payload.get("document_name") != detail.document_name
            ):
                return None
            interrupt = run.request_payload.get("graph_interrupt")
            value = interrupt.get("value", interrupt) if isinstance(interrupt, dict) else None
            if (
                not isinstance(value, dict)
                or value.get("type") != "approval_request"
                or value.get("approval_uid") != approval.get_uid()
                or value.get("thread_id") != run.graph_thread_id
                or value.get("session_id") != run.graph_session_id
                or value.get("status") != "pending"
            ):
                return None

            run.status = InternalBotRunStatus.Resuming
            run.attempt += 1
            run.lease_expires_at = SafeDateTime.now() + timedelta(seconds=lease_seconds)
            run.request_payload = {
                **run.request_payload,
                "resume": dict(decision),
                "resume_actor_uid": approver_id.to_short_code(),
            }
            db.update(run)
            return run

    def complete_editor_resume(
        self,
        run_id: SnowflakeID,
        attempt: int,
        response_text: str,
        next_interrupt: dict[str, Any] | None,
        next_approval: GraphApprovalRequest | None,
    ) -> EditorResumeResult | None:
        if (next_interrupt is None) != (next_approval is None):
            raise ValueError("A new editor approval requires a matching Graph interrupt")
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("attempt") == attempt)
                    & InternalBotRun.column("kind").in_(
                        (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                    )
                )
                .with_for_update()
            ).first()
            if run is None:
                return None

            marker = run.request_payload.get("resume_result")
            if run.status in (InternalBotRunStatus.Completed, InternalBotRunStatus.AwaitingApproval):
                if not isinstance(marker, dict) or marker.get("attempt") != attempt or run.output_text != response_text:
                    return None
                saved_next = run.request_payload.get("graph_interrupt")
                if next_interrupt is None:
                    return EditorResumeResult(run, None, None, False) if saved_next is None else None
                if not isinstance(saved_next, dict) or self._original_interrupt(saved_next) != next_interrupt:
                    return None
                return EditorResumeResult(run, None, None, False)
            if run.status != InternalBotRunStatus.Resuming or not run.graph_thread_id or not run.graph_session_id:
                return None

            original_interrupt = run.request_payload.get("graph_interrupt")
            original_value = (
                original_interrupt.get("value", original_interrupt) if isinstance(original_interrupt, dict) else None
            )
            decision = run.request_payload.get("resume")
            actor_uid = run.request_payload.get("resume_actor_uid")
            if (
                not isinstance(original_interrupt, dict)
                or not isinstance(original_value, dict)
                or not isinstance(decision, dict)
                or not isinstance(actor_uid, str)
                or not isinstance(original_value.get("approval_uid"), str)
            ):
                return None
            approval_id = SnowflakeID.from_short_code(original_value["approval_uid"])
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest)
                .where(
                    (GraphApprovalRequest.column("id") == approval_id)
                    & (GraphApprovalRequest.column("thread_id") == run.graph_thread_id)
                )
                .with_for_update()
            ).first()
            if (
                approval is None
                or approval.request_type != GraphApprovalOriginType.Editor
                or approval.requested_by_user_id != run.user_id
                or approval.status != GraphApprovalStatus.Pending
            ):
                return None

            if decision.get("approved") is True and decision.get("rejected") is False:
                resolved_status = GraphApprovalStatus.Approved
            elif decision.get("rejected") is True and decision.get("approved") is False:
                resolved_status = GraphApprovalStatus.Rejected
            else:
                return None
            if next_interrupt is not None and (
                next_approval is None
                or not run.scope_uid
                or next_approval.thread_id != run.graph_thread_id
                or next_approval.requested_by_user_id != run.user_id
            ):
                return None

            now = SafeDateTime.now()
            approval.status = resolved_status
            approval.resolved_by_user_id = SnowflakeID.from_short_code(actor_uid)
            approval.resolved_at = now
            reason = decision.get("reason")
            approval.rejection_reason = (
                reason if resolved_status == GraphApprovalStatus.Rejected and isinstance(reason, str) else None
            )
            db.update(approval)

            resolved_value = {
                **original_value,
                "status": resolved_status.value,
                "resolved_by_user_uid": actor_uid,
                "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            if approval.rejection_reason:
                resolved_value["rejection_reason"] = approval.rejection_reason
            saved_original = (
                {**original_interrupt, "value": resolved_value} if "value" in original_interrupt else resolved_value
            )
            saved_next = None
            if next_interrupt is not None and next_approval is not None and run.scope_uid:
                db.insert(next_approval)
                detail = EditorGraphApprovalRequest.create_for_approval(
                    next_approval,
                    run.scope_table,
                    SnowflakeID.from_short_code(run.scope_uid),
                    document_name=run.request_payload.get("document_name"),
                )
                detail.approval_request_id = next_approval.id
                db.insert(detail)
                value = next_interrupt.get("value", next_interrupt)
                enriched = {**value, "approval_uid": next_approval.get_uid(), "status": "pending"}
                saved_next = {**next_interrupt, "value": enriched} if "value" in next_interrupt else enriched

            run.request_payload = {
                **run.request_payload,
                "resolved_interrupt": saved_original,
                "graph_interrupt": saved_next,
                "resume_result": {"attempt": attempt, "approval_uid": approval.get_uid()},
            }
            run.status = (
                InternalBotRunStatus.AwaitingApproval if saved_next is not None else InternalBotRunStatus.Completed
            )
            run.output_text = response_text
            run.lease_expires_at = None
            run.finished_at = None if saved_next is not None else now
            db.update(run)
            return EditorResumeResult(run, approval, next_approval, True)

    def fail_editor_resume(self, run_id: SnowflakeID, attempt: int, error_message: str) -> EditorResumeFailure | None:
        normalized_error = error_message[:1000]
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("attempt") == attempt)
                    & InternalBotRun.column("kind").in_(
                        (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                    )
                )
                .with_for_update()
            ).first()
            if run is None:
                return None

            marker = run.request_payload.get("resume_failure")
            if run.status == InternalBotRunStatus.Failed:
                if (
                    isinstance(marker, dict)
                    and marker.get("attempt") == attempt
                    and run.error_message == normalized_error
                ):
                    return EditorResumeFailure(run, None, False)
                return None
            if run.status != InternalBotRunStatus.Resuming:
                return None

            interrupt = run.request_payload.get("graph_interrupt")
            if not isinstance(interrupt, dict):
                return None
            value = interrupt.get("value", interrupt)
            if not isinstance(value, dict) or not isinstance(value.get("approval_uid"), str):
                return None
            approval_id = SnowflakeID.from_short_code(value["approval_uid"])
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest)
                .where(
                    (GraphApprovalRequest.column("id") == approval_id)
                    & (GraphApprovalRequest.column("thread_id") == run.graph_thread_id)
                    & (GraphApprovalRequest.column("requested_by_user_id") == run.user_id)
                    & (GraphApprovalRequest.column("status") == GraphApprovalStatus.Pending)
                )
                .with_for_update()
            ).first()
            if approval is None or approval.request_type != GraphApprovalOriginType.Editor:
                return None

            now = SafeDateTime.now()
            approval.status = GraphApprovalStatus.Expired
            approval.resolved_at = now
            db.update(approval)
            resolved_value = {
                **value,
                "status": GraphApprovalStatus.Expired.value,
                "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            saved_interrupt = {**interrupt, "value": resolved_value} if "value" in interrupt else resolved_value
            run.request_payload = {
                **run.request_payload,
                "graph_interrupt": saved_interrupt,
                "resume_failure": {"attempt": attempt, "approval_uid": approval.get_uid()},
            }
            run.status = InternalBotRunStatus.Failed
            run.output_text = ""
            run.error_message = normalized_error
            run.lease_expires_at = None
            run.finished_at = now
            db.update(run)
            return EditorResumeFailure(run, approval, True)

    def close_board_chat_approval(
        self, approval_id: SnowflakeID, status: GraphApprovalStatus, reason: str
    ) -> GraphApprovalRequest | None:
        if status not in (GraphApprovalStatus.Expired, GraphApprovalStatus.Cancelled):
            raise ValueError("A Board chat approval can only be expired or cancelled here")
        with DbSession.use(readonly=False) as db:
            detail = db.exec(
                SqlBuilder.select.table(ChatGraphApprovalRequest).where(
                    ChatGraphApprovalRequest.column("approval_request_id") == approval_id
                )
            ).first()
            if detail is None:
                return None
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("chat_session_id") == detail.chat_session_id)
                    & (InternalBotRun.column("ai_chat_history_id") == detail.chat_history_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                    & (InternalBotRun.column("status") == InternalBotRunStatus.AwaitingApproval)
                )
                .with_for_update()
            ).first()
            if run is None:
                return None
            approval = db.exec(
                SqlBuilder.select.table(GraphApprovalRequest)
                .where(GraphApprovalRequest.column("id") == approval_id)
                .with_for_update()
            ).first()
            message = db.exec(
                SqlBuilder.select.table(ChatHistory)
                .where(
                    (ChatHistory.column("id") == detail.chat_history_id)
                    & (ChatHistory.column("chat_session_id") == detail.chat_session_id)
                    & ChatHistory.column("is_received").is_(True)
                )
                .with_for_update()
            ).first()
            if (
                approval is None
                or message is None
                or approval.status != GraphApprovalStatus.Pending
                or approval.thread_id != run.graph_thread_id
                or approval.requested_by_user_id != run.user_id
            ):
                return None
            interrupt = message.message.graph_interrupt
            if not isinstance(interrupt, dict):
                return None
            value = interrupt.get("value", interrupt)
            if not isinstance(value, dict) or value.get("approval_uid") != approval.get_uid():
                return None

            now = SafeDateTime.now()
            approval.status = status
            approval.resolved_at = now
            db.update(approval)
            resolved_value = {
                **value,
                "status": status.value,
                "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            saved_interrupt = {**interrupt, "value": resolved_value} if "value" in interrupt else resolved_value
            message.message = ChatContentModel(content=message.message.content, graph_interrupt=saved_interrupt)
            db.update(message)
            run.status = (
                InternalBotRunStatus.Failed if status == GraphApprovalStatus.Expired else InternalBotRunStatus.Cancelled
            )
            run.error_message = reason[:1000]
            run.lease_expires_at = None
            run.finished_at = now
            db.update(run)
            return approval

    def set_graph_identity(
        self, run_id: SnowflakeID, attempt: int, session_id: str, thread_id: str
    ) -> ChatHistory | None:
        if not session_id or not thread_id:
            raise ValueError("Graph session and thread identifiers are required")
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("attempt") == attempt)
                    & (InternalBotRun.column("status") == InternalBotRunStatus.Streaming)
                )
                .with_for_update()
            ).first()
            if (
                run is None
                or run.kind != InternalBotRunKind.BoardChat
                or run.chat_session_id is None
                or run.graph_thread_id is not None
            ):
                return None

            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession)
                .where(ChatSession.column("id") == run.chat_session_id)
                .with_for_update()
            ).first()
            if chat_session is None or chat_session.user_id != run.user_id:
                raise RuntimeError("The claimed AI run has no owned chat session")

            ai_message = ChatHistory(
                chat_session_id=run.chat_session_id,
                message=ChatContentModel(content=""),
                is_received=True,
            )
            db.insert(ai_message)
            run.ai_chat_history_id = ai_message.id
            run.graph_session_id = session_id
            run.graph_thread_id = thread_id
            db.update(run)

            chat_session.last_messaged_at = ai_message.created_at
            db.update(chat_session)
            return ai_message

    def set_editor_graph_identity(self, run_id: SnowflakeID, attempt: int, session_id: str, thread_id: str) -> bool:
        if not session_id or not thread_id:
            raise ValueError("Graph session and thread identifiers are required")
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("attempt") == attempt)
                    & (InternalBotRun.column("status") == InternalBotRunStatus.Streaming)
                )
                .with_for_update()
            ).first()
            if (
                run is None
                or run.kind not in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                or run.graph_thread_id is not None
            ):
                return False
            run.graph_session_id = session_id
            run.graph_thread_id = thread_id
            db.update(run)
            return True

    def mark_expired_uncertain(self, now: SafeDateTime, limit: int) -> list[InternalBotRun]:
        if limit <= 0:
            return []
        # Accepted runs have not started Graph and remain safe for a recovery scanner to claim.
        with DbSession.use(readonly=False) as db:
            runs = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    InternalBotRun.column("status").in_(
                        (
                            InternalBotRunStatus.Streaming,
                            InternalBotRunStatus.Resuming,
                        )
                    )
                    & (InternalBotRun.column("lease_expires_at") < now)
                )
                .order_by(InternalBotRun.column("lease_expires_at"), InternalBotRun.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for run in runs:
                if run.kind == InternalBotRunKind.BoardChat and run.ai_chat_history_id is not None:
                    ai_message = db.exec(
                        SqlBuilder.select.table(ChatHistory)
                        .where(
                            (ChatHistory.column("id") == run.ai_chat_history_id)
                            & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                            & ChatHistory.column("is_received").is_(True)
                        )
                        .with_for_update()
                    ).first()
                    if (
                        ai_message is not None
                        and ai_message.message.content == ""
                        and ai_message.message.graph_interrupt is None
                    ):
                        db.delete(ai_message)
                run.status = InternalBotRunStatus.Uncertain
                run.error_message = "AI worker lease expired before a terminal result"
                db.update(run)
            return runs

    def renew_lease(self, run_id: SnowflakeID, attempt: int, lease_seconds: int) -> bool:
        if lease_seconds <= 0:
            raise ValueError("The AI run lease must be positive")
        now = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            return (
                db.exec(
                    SqlBuilder.update.table(InternalBotRun)
                    .values(
                        {
                            InternalBotRun.column("lease_expires_at"): now + timedelta(seconds=lease_seconds),
                            InternalBotRun.column("updated_at"): now,
                        }
                    )
                    .where(
                        (InternalBotRun.column("id") == run_id)
                        & (InternalBotRun.column("attempt") == attempt)
                        & InternalBotRun.column("status").in_(
                            (InternalBotRunStatus.Streaming, InternalBotRunStatus.Resuming)
                        )
                    )
                )
                == 1
            )

    def pause_board_chat(
        self,
        run_id: SnowflakeID,
        attempt: int,
        output_text: str,
        interrupt: dict[str, Any],
        approval: GraphApprovalRequest | None,
    ) -> tuple[dict[str, Any], bool] | None:
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where((InternalBotRun.column("id") == run_id) & (InternalBotRun.column("attempt") == attempt))
                .with_for_update()
            ).first()
            if (
                run is None
                or run.kind != InternalBotRunKind.BoardChat
                or run.chat_session_id is None
                or run.ai_chat_history_id is None
                or run.graph_thread_id is None
            ):
                return None

            ai_message = db.exec(
                SqlBuilder.select.table(ChatHistory)
                .where(
                    (ChatHistory.column("id") == run.ai_chat_history_id)
                    & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    & ChatHistory.column("is_received").is_(True)
                )
                .with_for_update()
            ).first()
            if ai_message is None:
                return None

            if run.status == InternalBotRunStatus.AwaitingApproval:
                saved_interrupt = ai_message.message.graph_interrupt
                if (
                    run.output_text == output_text
                    and saved_interrupt is not None
                    and self._original_interrupt(saved_interrupt) == interrupt
                ):
                    return saved_interrupt, False
                return None
            if run.status != InternalBotRunStatus.Streaming:
                return None

            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession)
                .where(
                    (ChatSession.column("id") == run.chat_session_id) & (ChatSession.column("user_id") == run.user_id)
                )
                .with_for_update()
            ).first()
            if chat_session is None:
                return None

            saved_interrupt = dict(interrupt)
            if approval is not None:
                saved_interrupt = self._insert_board_chat_approval(
                    db, run, chat_session, ai_message, interrupt, approval
                )

            ai_message.message = ChatContentModel(content=output_text, graph_interrupt=saved_interrupt)
            db.update(ai_message)
            chat_session.last_messaged_at = ai_message.updated_at
            db.update(chat_session)
            run.status = InternalBotRunStatus.AwaitingApproval
            run.output_text = output_text
            run.lease_expires_at = None
            db.update(run)
            return saved_interrupt, True

    def pause_editor(
        self,
        run_id: SnowflakeID,
        attempt: int,
        output_text: str,
        interrupt: dict[str, Any],
        approval: GraphApprovalRequest,
    ) -> tuple[dict[str, Any], bool] | None:
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where((InternalBotRun.column("id") == run_id) & (InternalBotRun.column("attempt") == attempt))
                .with_for_update()
            ).first()
            if (
                run is None
                or run.kind not in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot)
                or run.graph_thread_id != approval.thread_id
                or not run.scope_uid
            ):
                return None

            if run.status == InternalBotRunStatus.AwaitingApproval:
                saved_interrupt = run.request_payload.get("graph_interrupt")
                if (
                    run.output_text == output_text
                    and isinstance(saved_interrupt, dict)
                    and self._original_interrupt(saved_interrupt) == interrupt
                ):
                    return saved_interrupt, False
                return None
            if run.status != InternalBotRunStatus.Streaming:
                return None

            db.insert(approval)
            detail = EditorGraphApprovalRequest.create_for_approval(
                approval,
                run.scope_table,
                SnowflakeID.from_short_code(run.scope_uid),
                document_name=run.request_payload.get("document_name"),
            )
            detail.approval_request_id = approval.id
            db.insert(detail)
            value = interrupt.get("value", interrupt)
            enriched = {**value, "approval_uid": approval.get_uid(), "status": "pending"}
            saved_interrupt = {**interrupt, "value": enriched} if "value" in interrupt else enriched
            run.request_payload = {**run.request_payload, "graph_interrupt": saved_interrupt}
            run.status = InternalBotRunStatus.AwaitingApproval
            run.output_text = output_text
            run.lease_expires_at = None
            db.update(run)
            return saved_interrupt, True

    @staticmethod
    def _insert_board_chat_approval(
        db: DbSession,
        run: InternalBotRun,
        chat_session: ChatSession,
        ai_message: ChatHistory,
        interrupt: dict[str, Any],
        approval: GraphApprovalRequest,
    ) -> dict[str, Any]:
        db.insert(approval)
        scope_id = run.project_id if run.scope_table == "project" else SnowflakeID.from_short_code(run.scope_uid or "")
        detail = ChatGraphApprovalRequest.create_for_approval(
            approval, run.scope_table, scope_id, chat_session=chat_session, chat_history=ai_message
        )
        detail.approval_request_id = approval.id
        db.insert(detail)
        value = interrupt.get("value", interrupt)
        enriched = {**value, "approval_uid": approval.get_uid(), "status": "pending"}
        return {**interrupt, "value": enriched} if "value" in interrupt else enriched

    def claim_board_chat_resume(
        self,
        project_id: SnowflakeID,
        user_id: SnowflakeID,
        ai_message_id: SnowflakeID,
        thread_id: str,
        session_id: str,
        approval_id: SnowflakeID | None,
        resume: Mapping[str, bool | str],
        lease_seconds: int,
    ) -> InternalBotRun | None:
        if lease_seconds <= 0:
            raise ValueError("The AI run lease must be positive")

        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("project_id") == project_id)
                    & (InternalBotRun.column("user_id") == user_id)
                    & (InternalBotRun.column("ai_chat_history_id") == ai_message_id)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
                .with_for_update()
            ).first()
            if (
                run is None
                or run.status != InternalBotRunStatus.AwaitingApproval
                or run.chat_session_id is None
                or run.graph_thread_id != thread_id
                or run.graph_session_id != session_id
            ):
                return None

            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession).where(
                    (ChatSession.column("id") == run.chat_session_id) & (ChatSession.column("user_id") == user_id)
                )
            ).first()
            project_session = db.exec(
                SqlBuilder.select.table(ProjectChatSession).where(
                    (ProjectChatSession.column("project_id") == project_id)
                    & (ProjectChatSession.column("chat_session_id") == run.chat_session_id)
                )
            ).first()
            ai_message = db.exec(
                SqlBuilder.select.table(ChatHistory).where(
                    (ChatHistory.column("id") == ai_message_id)
                    & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    & ChatHistory.column("is_received").is_(True)
                )
            ).first()
            if chat_session is None or project_session is None or ai_message is None:
                return None

            interrupt = ai_message.message.graph_interrupt
            if not isinstance(interrupt, dict):
                return None
            value = interrupt.get("value", interrupt)
            if (
                not isinstance(value, dict)
                or value.get("thread_id") != thread_id
                or value.get("session_id") != session_id
            ):
                return None
            saved_approval_uid = value.get("approval_uid")
            if value.get("status") not in (None, "pending"):
                return None
            if approval_id is None:
                if saved_approval_uid is not None or value.get("type") == "approval_request":
                    return None
            else:
                if value.get("type") != "approval_request" or saved_approval_uid != approval_id.to_short_code():
                    return None
                approval = db.exec(
                    SqlBuilder.select.table(GraphApprovalRequest).where(
                        (GraphApprovalRequest.column("id") == approval_id)
                        & (GraphApprovalRequest.column("thread_id") == thread_id)
                    )
                ).first()
                detail = db.exec(
                    SqlBuilder.select.table(ChatGraphApprovalRequest).where(
                        (ChatGraphApprovalRequest.column("approval_request_id") == approval_id)
                        & (ChatGraphApprovalRequest.column("chat_session_id") == run.chat_session_id)
                        & (ChatGraphApprovalRequest.column("chat_history_id") == ai_message_id)
                    )
                ).first()
                if (
                    approval is None
                    or detail is None
                    or approval.request_type != GraphApprovalOriginType.Chat
                    or approval.requested_by_user_id != user_id
                    or approval.status != GraphApprovalStatus.Pending
                    or detail.scope_table != run.scope_table
                    or self._approval_expired(approval)
                ):
                    return None

            now = SafeDateTime.now()
            run.status = InternalBotRunStatus.Resuming
            run.attempt += 1
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            run.request_payload = {**run.request_payload, "resume": dict(resume)}
            db.update(run)
            return run

    def complete_board_chat_resume(
        self,
        run_id: SnowflakeID,
        attempt: int,
        response_text: str,
        next_interrupt: dict[str, Any] | None,
        next_approval: GraphApprovalRequest | None,
    ) -> BoardChatResumeResult | None:
        if next_approval is not None and next_interrupt is None:
            raise ValueError("A new approval requires a Graph interrupt")

        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where(
                    (InternalBotRun.column("id") == run_id)
                    & (InternalBotRun.column("attempt") == attempt)
                    & (InternalBotRun.column("kind") == InternalBotRunKind.BoardChat)
                )
                .with_for_update()
            ).first()
            if run is None or run.chat_session_id is None or run.ai_chat_history_id is None:
                return None

            marker = run.request_payload.get("resume_result")
            if run.status in (InternalBotRunStatus.Completed, InternalBotRunStatus.AwaitingApproval):
                if not isinstance(marker, dict) or marker.get("attempt") != attempt or run.output_text != response_text:
                    return None
                source_uid = marker.get("source_message_uid")
                resumed_uid = marker.get("resumed_message_uid")
                if not isinstance(source_uid, str):
                    return None
                source = db.exec(
                    SqlBuilder.select.table(ChatHistory).where(
                        (ChatHistory.column("id") == SnowflakeID.from_short_code(source_uid))
                        & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    )
                ).first()
                resumed = (
                    db.exec(
                        SqlBuilder.select.table(ChatHistory).where(
                            (ChatHistory.column("id") == SnowflakeID.from_short_code(resumed_uid))
                            & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                        )
                    ).first()
                    if isinstance(resumed_uid, str)
                    else None
                )
                if source is None or (resumed_uid is not None and resumed is None):
                    return None
                if next_interrupt is not None:
                    if (
                        run.status != InternalBotRunStatus.AwaitingApproval
                        or resumed is None
                        or resumed.message.graph_interrupt is None
                        or self._original_interrupt(resumed.message.graph_interrupt) != next_interrupt
                    ):
                        return None
                elif run.status != InternalBotRunStatus.Completed:
                    return None
                return BoardChatResumeResult(run, source, resumed, None, None, False)

            if run.status != InternalBotRunStatus.Resuming:
                return None
            if next_interrupt is not None:
                value = next_interrupt.get("value", next_interrupt)
                if (
                    not isinstance(value, dict)
                    or value.get("thread_id") != run.graph_thread_id
                    or value.get("session_id") != run.graph_session_id
                    or (value.get("type") == "approval_request") != (next_approval is not None)
                ):
                    return None

            source = db.exec(
                SqlBuilder.select.table(ChatHistory)
                .where(
                    (ChatHistory.column("id") == run.ai_chat_history_id)
                    & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                    & ChatHistory.column("is_received").is_(True)
                )
                .with_for_update()
            ).first()
            chat_session = db.exec(
                SqlBuilder.select.table(ChatSession)
                .where(
                    (ChatSession.column("id") == run.chat_session_id) & (ChatSession.column("user_id") == run.user_id)
                )
                .with_for_update()
            ).first()
            if source is None or chat_session is None:
                return None
            original_interrupt = source.message.graph_interrupt
            if not isinstance(original_interrupt, dict):
                return None
            original_value = original_interrupt.get("value", original_interrupt)
            if not isinstance(original_value, dict):
                return None
            decision = run.request_payload.get("resume")
            if not isinstance(decision, dict):
                return None

            resolved_approval = None
            approval_uid = original_value.get("approval_uid")
            if isinstance(approval_uid, str):
                resolved_approval = db.exec(
                    SqlBuilder.select.table(GraphApprovalRequest)
                    .where(
                        (GraphApprovalRequest.column("id") == SnowflakeID.from_short_code(approval_uid))
                        & (GraphApprovalRequest.column("thread_id") == run.graph_thread_id)
                    )
                    .with_for_update()
                ).first()
                if resolved_approval is None or resolved_approval.status != GraphApprovalStatus.Pending:
                    return None

            now = SafeDateTime.now()
            if decision.get("approved") is True:
                resolved_status = GraphApprovalStatus.Approved
            elif decision.get("rejected") is True:
                resolved_status = GraphApprovalStatus.Rejected
            elif isinstance(decision.get("instruction"), str) and decision["instruction"].strip():
                resolved_status = GraphApprovalStatus.Resolved
            else:
                return None

            if resolved_approval is not None:
                resolved_approval.status = resolved_status
                resolved_approval.resolved_by_user_id = run.user_id
                resolved_approval.resolved_at = now
                reason = decision.get("reason")
                resolved_approval.rejection_reason = (
                    reason if resolved_status == GraphApprovalStatus.Rejected and isinstance(reason, str) else None
                )
                db.update(resolved_approval)

            resolved_value = {
                **original_value,
                "status": resolved_status.value,
                "resolved_by_user_uid": run.user_id.to_short_code(),
                "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            instruction = decision.get("instruction")
            if isinstance(instruction, str) and instruction:
                resolved_value["instruction"] = instruction
            if resolved_approval is not None and resolved_approval.rejection_reason:
                resolved_value["rejection_reason"] = resolved_approval.rejection_reason
            saved_original_interrupt = (
                {**original_interrupt, "value": resolved_value} if "value" in original_interrupt else resolved_value
            )
            source.message = ChatContentModel(content=source.message.content, graph_interrupt=saved_original_interrupt)
            db.update(source)

            resumed_message = None
            if next_interrupt is not None or (
                resolved_status != GraphApprovalStatus.Rejected
                and response_text.strip()
                and response_text.strip() != source.message.content.strip()
            ):
                resumed_message = ChatHistory(
                    chat_session_id=run.chat_session_id,
                    message=ChatContentModel(content=response_text),
                    is_received=True,
                )
                db.insert(resumed_message)
                if next_interrupt is not None:
                    saved_next_interrupt = (
                        self._insert_board_chat_approval(
                            db, run, chat_session, resumed_message, next_interrupt, next_approval
                        )
                        if next_approval is not None
                        else next_interrupt
                    )
                    resumed_message.message = ChatContentModel(
                        content=response_text, graph_interrupt=saved_next_interrupt
                    )
                    db.update(resumed_message)
                    run.ai_chat_history_id = resumed_message.id

            chat_session.last_messaged_at = (
                resumed_message.created_at if resumed_message is not None else source.updated_at
            )
            db.update(chat_session)
            run.status = (
                InternalBotRunStatus.AwaitingApproval if next_interrupt is not None else InternalBotRunStatus.Completed
            )
            run.output_text = response_text
            run.lease_expires_at = None
            run.finished_at = now if next_interrupt is None else None
            run.request_payload = {
                **run.request_payload,
                "resume_result": {
                    "attempt": attempt,
                    "source_message_uid": source.get_uid(),
                    "resumed_message_uid": resumed_message.get_uid() if resumed_message is not None else None,
                },
            }
            db.update(run)
            return BoardChatResumeResult(run, source, resumed_message, resolved_approval, next_approval, True)

    @staticmethod
    def _original_interrupt(interrupt: dict[str, Any]) -> dict[str, Any]:
        original = dict(interrupt)
        value = original.get("value", original)
        if isinstance(value, dict) and value.get("type") == "approval_request":
            original_value = dict(value)
            original_value.pop("approval_uid", None)
            original_value.pop("status", None)
            if "value" in original:
                original["value"] = original_value
            else:
                original = original_value
        return original

    @staticmethod
    def _approval_expired(approval: GraphApprovalRequest) -> bool:
        expires_at = approval.expires_at
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= SafeDateTime.now()

    def finish(
        self,
        run_id: SnowflakeID,
        attempt: int,
        status: InternalBotRunStatus,
        output_text: str = "",
        error_message: str | None = None,
    ) -> bool:
        if status not in {
            InternalBotRunStatus.Completed,
            InternalBotRunStatus.Failed,
            InternalBotRunStatus.Cancelled,
        }:
            raise ValueError("A run can only finish with a terminal status")

        now = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            run = db.exec(
                SqlBuilder.select.table(InternalBotRun)
                .where((InternalBotRun.column("id") == run_id) & (InternalBotRun.column("attempt") == attempt))
                .with_for_update()
            ).first()
            if run is None:
                return False
            normalized_error = error_message[:1000] if error_message else None
            if run.status != InternalBotRunStatus.Streaming:
                return run.status == status and run.output_text == output_text and run.error_message == normalized_error

            if run.kind == InternalBotRunKind.BoardChat and run.ai_chat_history_id is not None:
                ai_message = db.exec(
                    SqlBuilder.select.table(ChatHistory).where(
                        (ChatHistory.column("id") == run.ai_chat_history_id)
                        & (ChatHistory.column("chat_session_id") == run.chat_session_id)
                        & ChatHistory.column("is_received").is_(True)
                    )
                ).first()
                if ai_message is None:
                    raise RuntimeError("The AI run has no bound response message")

                if status == InternalBotRunStatus.Failed or (
                    status == InternalBotRunStatus.Cancelled and not output_text
                ):
                    db.delete(ai_message)
                else:
                    ai_message.message = ChatContentModel(content=output_text)
                    db.update(ai_message)
                    chat_session = db.exec(
                        SqlBuilder.select.table(ChatSession).where(
                            (ChatSession.column("id") == run.chat_session_id)
                            & (ChatSession.column("user_id") == run.user_id)
                        )
                    ).first()
                    if chat_session is None:
                        raise RuntimeError("The AI run has no owned chat session")
                    chat_session.last_messaged_at = ai_message.updated_at
                    db.update(chat_session)

            run.status = status
            run.output_text = output_text
            run.error_message = normalized_error
            run.lease_expires_at = None
            run.finished_at = now
            db.update(run)
            return True

    def get_by_id(self, run_id: SnowflakeID) -> InternalBotRun | None:
        with DbSession.use(readonly=False) as db:
            return db.exec(SqlBuilder.select.table(InternalBotRun).where(InternalBotRun.column("id") == run_id)).first()
