from datetime import timedelta
from hashlib import sha256
from json import dumps
from typing import Any
from uuid import UUID
from ....ai.InternalBotGraphRequest import build_board_chat_bot_request, build_editor_graph_request
from ....core.domain import BaseDomainService
from ....core.routing import EEditorCollaborationType
from ....core.types import SafeDateTime, SnowflakeID
from ....Env import Env
from ...models import ChatHistory, ChatSession, GraphApprovalRequest, InternalBotRun, ProjectChatSession
from ...models.InternalBot import InternalBot
from ...models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from ...models.ProjectAssignedInternalBot import ProjectAssignedInternalBot
from ...models.User import User
from .GraphApprovalRequestService import GraphApprovalRequestService
from .ProjectService import ProjectService


class InternalBotRunService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "internal_bot_run"

    def accept_board_chat(
        self,
        *,
        task_id: UUID,
        user_id: SnowflakeID,
        project_id: SnowflakeID,
        internal_bot_id: SnowflakeID,
        project_chat_session_id: SnowflakeID | None,
        message: str,
        permission_level: str,
        scope_table: str,
        scope_uid: str | None,
        attachment: dict[str, str] | None = None,
    ) -> tuple[InternalBotRun, bool, ChatSession, ProjectChatSession, ChatHistory]:
        request_key = self._board_chat_request_key(task_id, user_id, project_id)
        request_payload: dict[str, Any] = {"message": message, "api_permission_level": permission_level}
        if attachment is not None:
            attachment_values = {key: attachment.get(key) for key in ("file_id", "path", "token")}
            if not all(isinstance(value, str) and value for value in attachment_values.values()):
                raise ValueError("Board chat attachment payload is invalid")
            request_payload["attachment"] = {
                key: value for key, value in attachment_values.items() if isinstance(value, str)
            }
        request_digest = sha256(
            dumps(
                {
                    "internal_bot_id": int(internal_bot_id),
                    "scope_table": scope_table,
                    "scope_uid": scope_uid,
                    "request_payload": request_payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        candidate = InternalBotRun(
            request_key=request_key,
            request_digest=request_digest,
            client_task_id=str(task_id),
            user_id=user_id,
            project_id=project_id,
            internal_bot_id=internal_bot_id,
            chat_session_id=None,
            kind=InternalBotRunKind.BoardChat,
            scope_table=scope_table,
            scope_uid=scope_uid,
            request_payload=request_payload,
            lease_expires_at=SafeDateTime.now() + timedelta(seconds=Env.AI_REQUEST_TIMEOUT + 30),
        )
        return self.repo.internal_bot_run.accept_board_chat(
            candidate, message, permission_level, project_chat_session_id
        )

    def accept_editor(
        self,
        *,
        kind: InternalBotRunKind,
        task_id: UUID,
        user_id: SnowflakeID,
        project_id: SnowflakeID,
        internal_bot_id: SnowflakeID,
        scope_table: str,
        scope_uid: str,
        document_name: str,
        system: str,
        messages: list[dict[str, str]] | None,
        prompt: str | None,
    ) -> tuple[InternalBotRun, bool]:
        document_types = {
            "card": EEditorCollaborationType.Card.value,
            "project_wiki": EEditorCollaborationType.Wiki.value,
        }
        document_type = document_types.get(scope_table)
        if not document_type or not scope_uid or not document_name.startswith(f"{document_type}:{scope_uid}:"):
            raise ValueError("Editor AI document scope is invalid")

        request_payload: dict[str, Any] = {"document_name": document_name, "system": system}
        if kind == InternalBotRunKind.EditorChat and messages and prompt is None:
            request_payload["messages"] = messages
        elif kind == InternalBotRunKind.EditorCopilot and prompt and messages is None:
            request_payload["prompt"] = prompt
        else:
            raise ValueError("Editor AI request payload is invalid")

        request_key = self._editor_request_key(kind, task_id, user_id, project_id)
        request_digest = sha256(
            dumps(
                {
                    "internal_bot_id": int(internal_bot_id),
                    "scope_table": scope_table,
                    "scope_uid": scope_uid,
                    "request_payload": request_payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        candidate = InternalBotRun(
            request_key=request_key,
            request_digest=request_digest,
            client_task_id=str(task_id),
            user_id=user_id,
            project_id=project_id,
            internal_bot_id=internal_bot_id,
            kind=kind,
            scope_table=scope_table,
            scope_uid=scope_uid,
            request_payload=request_payload,
            lease_expires_at=SafeDateTime.now() + timedelta(seconds=Env.AI_REQUEST_TIMEOUT + 30),
        )
        return self.repo.internal_bot_run.accept(candidate)

    def start_editor(
        self,
        run_id: SnowflakeID,
        bot: InternalBot,
        user: User,
        assignment: ProjectAssignedInternalBot,
        lease_seconds: int,
    ) -> tuple[InternalBotRun, dict[str, Any]] | None:
        run = self.repo.internal_bot_run.claim(run_id, lease_seconds)
        if run is None:
            return None
        try:
            graph_request = build_editor_graph_request(run, bot, user, assignment)
        except ValueError as error:
            self.repo.internal_bot_run.finish(
                run.id, run.attempt, InternalBotRunStatus.Failed, error_message=str(error)
            )
            raise
        if not self.repo.internal_bot_run.set_editor_graph_identity(
            run.id, run.attempt, graph_request["session_id"], graph_request["thread_id"]
        ):
            self.repo.internal_bot_run.finish(
                run.id, run.attempt, InternalBotRunStatus.Failed, error_message="Graph identity could not be persisted"
            )
            raise RuntimeError("The claimed editor AI run lost its Graph identity fence")
        return run, graph_request

    def get_editor_run(self, run_id: SnowflakeID) -> InternalBotRun | None:
        run = self.repo.internal_bot_run.get_by_id(run_id)
        return run if run and run.kind in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot) else None

    def get_editor_run_by_task(
        self, kind: InternalBotRunKind, task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> InternalBotRun | None:
        return self.repo.internal_bot_run.get_editor_run_by_request_key(
            self._editor_request_key(kind, task_id, user_id, project_id), user_id, project_id, kind
        )

    def get_editor_run_by_approval(self, approval_id: SnowflakeID) -> InternalBotRun | None:
        return self.repo.internal_bot_run.get_editor_run_by_approval(approval_id)

    def list_accepted_editor_runs(self, limit: int, after_id: SnowflakeID | None = None) -> list[InternalBotRun]:
        return self.repo.internal_bot_run.list_accepted_editor_runs(limit, after_id)

    def finish_editor(
        self,
        run_id: SnowflakeID,
        attempt: int,
        status: InternalBotRunStatus,
        output_text: str,
        error_message: str | None,
    ) -> bool:
        return self.repo.internal_bot_run.finish(run_id, attempt, status, output_text, error_message)

    def pause_editor(
        self, run_id: SnowflakeID, attempt: int, output_text: str, interrupt: dict[str, Any]
    ) -> tuple[dict[str, Any], GraphApprovalRequest | None] | None:
        run = self.get_editor_run(run_id)
        if run is None:
            return None
        approval = self._get_service(GraphApprovalRequestService).prepare_editor_interrupt(run, interrupt)
        result = self.repo.internal_bot_run.pause_editor(run_id, attempt, output_text, interrupt, approval)
        if result is None:
            return None
        saved_interrupt, newly_applied = result
        return saved_interrupt, approval if newly_applied else None

    def claim_editor_resume(
        self,
        approval_id: SnowflakeID,
        project_id: SnowflakeID,
        approver_id: SnowflakeID,
        decision: dict[str, bool | str],
        lease_seconds: int,
    ) -> InternalBotRun | None:
        return self.repo.internal_bot_run.claim_editor_resume(
            approval_id, project_id, approver_id, decision, lease_seconds
        )

    def complete_editor_resume(
        self, run_id: SnowflakeID, attempt: int, response_text: str, next_interrupt: dict[str, Any] | None
    ) -> tuple[InternalBotRun, GraphApprovalRequest | None, GraphApprovalRequest | None, bool] | None:
        run = self.get_editor_run(run_id)
        if run is None:
            return None
        next_approval = (
            self._get_service(GraphApprovalRequestService).prepare_editor_interrupt(run, next_interrupt)
            if next_interrupt is not None
            else None
        )
        return self.repo.internal_bot_run.complete_editor_resume(
            run_id, attempt, response_text, next_interrupt, next_approval
        )

    def fail_editor_resume(
        self, run_id: SnowflakeID, attempt: int, error_message: str
    ) -> tuple[InternalBotRun, GraphApprovalRequest | None, bool] | None:
        return self.repo.internal_bot_run.fail_editor_resume(run_id, attempt, error_message)

    def renew_editor_lease(self, run_id: SnowflakeID, attempt: int, lease_seconds: int) -> bool:
        return self.repo.internal_bot_run.renew_lease(run_id, attempt, lease_seconds)

    def cancel_editor(
        self, kind: InternalBotRunKind, task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> InternalBotRun | None:
        request_key = self._editor_request_key(kind, task_id, user_id, project_id)
        run = self.repo.internal_bot_run.get_editor_run_by_request_key(request_key, user_id, project_id, kind)
        if run and run.status == InternalBotRunStatus.AwaitingApproval:
            project = self._get_service(ProjectService).get_by_id_like(project_id)
            if project:
                cancelled = self._get_service(GraphApprovalRequestService).cancel_editor_run(
                    run, project, reason="Editor AI run cancelled"
                )
                if cancelled:
                    return cancelled
        return self.repo.internal_bot_run.cancel_editor(request_key, user_id, project_id, kind)

    @staticmethod
    def _editor_request_key(
        kind: InternalBotRunKind, task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> str:
        if kind not in (InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot):
            raise ValueError("Only editor AI run kinds have an editor request key")
        return sha256(f"{kind.value}:{user_id}:{project_id}:{task_id}".encode()).hexdigest()

    def get_board_chat_context(
        self, run_id: SnowflakeID
    ) -> tuple[InternalBotRun, ProjectChatSession, ChatHistory] | None:
        return self.repo.internal_bot_run.get_board_chat_context(run_id)

    def get_board_chat_run(self, run_id: SnowflakeID) -> InternalBotRun | None:
        return self.repo.internal_bot_run.get_board_chat_run(run_id)

    def list_accepted_board_chat_runs(self, limit: int, after_id: SnowflakeID | None = None) -> list[InternalBotRun]:
        return self.repo.internal_bot_run.list_accepted_board_chat_runs(limit, after_id)

    def get_owned_board_chat_status(
        self, task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID
    ) -> tuple[InternalBotRun, ProjectChatSession, ChatHistory, ChatHistory | None] | None:
        request_key = self._board_chat_request_key(task_id, user_id, project_id)
        return self.repo.internal_bot_run.get_owned_board_chat_status(request_key, user_id, project_id)

    def cancel_board_chat(self, task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID) -> InternalBotRun | None:
        request_key = self._board_chat_request_key(task_id, user_id, project_id)
        return self.repo.internal_bot_run.cancel_board_chat(request_key, user_id, project_id)

    @staticmethod
    def _board_chat_request_key(task_id: UUID, user_id: SnowflakeID, project_id: SnowflakeID) -> str:
        return sha256(f"{InternalBotRunKind.BoardChat.value}:{user_id}:{project_id}:{task_id}".encode()).hexdigest()

    def get_board_chat_run_by_ai_message(
        self, project_id: SnowflakeID, user_id: SnowflakeID, ai_message_id: SnowflakeID
    ) -> InternalBotRun | None:
        return self.repo.internal_bot_run.get_board_chat_run_by_ai_message(project_id, user_id, ai_message_id)

    def start_board_chat(
        self,
        run_id: SnowflakeID,
        bot: InternalBot,
        user: User,
        assignment: ProjectAssignedInternalBot,
        project_session: ProjectChatSession,
        *,
        scope_context: dict[str, Any] | None,
        active_collaborative_documents: list[dict[str, Any]],
        lease_seconds: int,
    ) -> tuple[InternalBotRun, dict[str, Any], ChatHistory] | None:
        run = self.repo.internal_bot_run.claim(run_id, lease_seconds)
        if run is None:
            return None
        try:
            bot_request = build_board_chat_bot_request(
                run,
                bot,
                user,
                project_session,
                assignment,
                scope_context=scope_context,
                active_collaborative_documents=active_collaborative_documents,
            )
        except ValueError as error:
            self.repo.internal_bot_run.finish(
                run.id, run.attempt, InternalBotRunStatus.Failed, error_message=str(error)
            )
            raise
        ai_message = self.repo.internal_bot_run.set_graph_identity(
            run.id, run.attempt, bot_request["session_id"], bot_request["thread_id"]
        )
        if ai_message is None:
            self.repo.internal_bot_run.finish(
                run.id, run.attempt, InternalBotRunStatus.Failed, error_message="Graph identity could not be persisted"
            )
            raise RuntimeError("The claimed AI run lost its Graph identity fence")
        return run, bot_request, ai_message

    def finish_board_chat(
        self,
        run_id: SnowflakeID,
        attempt: int,
        status: InternalBotRunStatus,
        output_text: str,
        error_message: str | None,
    ) -> bool:
        return self.repo.internal_bot_run.finish(run_id, attempt, status, output_text, error_message)

    def pause_board_chat(
        self, run_id: SnowflakeID, attempt: int, output_text: str, interrupt: dict[str, Any]
    ) -> tuple[dict[str, Any], GraphApprovalRequest | None] | None:
        run = self.repo.internal_bot_run.get_board_chat_run(run_id)
        if run is None:
            return None
        approval = self._get_service(GraphApprovalRequestService).prepare_board_chat_interrupt(run, interrupt)
        result = self.repo.internal_bot_run.pause_board_chat(run_id, attempt, output_text, interrupt, approval)
        if result is None:
            return None
        saved_interrupt, newly_applied = result
        return saved_interrupt, approval if newly_applied else None

    def renew_board_chat_lease(self, run_id: SnowflakeID, attempt: int, lease_seconds: int) -> bool:
        return self.repo.internal_bot_run.renew_lease(run_id, attempt, lease_seconds)

    def claim_board_chat_resume(
        self,
        project_id: SnowflakeID,
        user_id: SnowflakeID,
        ai_message_id: SnowflakeID,
        thread_id: str,
        session_id: str,
        approval_id: SnowflakeID | None,
        resume: dict[str, bool | str],
        lease_seconds: int,
    ) -> InternalBotRun | None:
        return self.repo.internal_bot_run.claim_board_chat_resume(
            project_id, user_id, ai_message_id, thread_id, session_id, approval_id, resume, lease_seconds
        )

    def complete_board_chat_resume(
        self,
        run_id: SnowflakeID,
        attempt: int,
        response_text: str,
        next_interrupt: dict[str, Any] | None,
    ) -> (
        tuple[
            InternalBotRun,
            ChatHistory,
            ChatHistory | None,
            GraphApprovalRequest | None,
            GraphApprovalRequest | None,
            bool,
        ]
        | None
    ):
        run = self.repo.internal_bot_run.get_board_chat_run(run_id)
        if run is None:
            return None
        next_approval = (
            self._get_service(GraphApprovalRequestService).prepare_board_chat_interrupt(run, next_interrupt)
            if next_interrupt is not None
            else None
        )
        return self.repo.internal_bot_run.complete_board_chat_resume(
            run_id, attempt, response_text, next_interrupt, next_approval
        )

    def recover_expired(self, limit: int = 100) -> list[InternalBotRun]:
        return self.repo.internal_bot_run.mark_expired_uncertain(SafeDateTime.now(), limit)
