from collections.abc import Iterator
from contextlib import nullcontext
from datetime import timedelta, timezone
from typing import Any
from unittest.mock import Mock
from uuid import uuid4
import langboard.commands.RunInternalBotRunRecoveryCommand as RecoveryCommandModule
import orjson
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langboard.commands.RunInternalBotRunRecoveryCommand import (
    RunInternalBotRunRecoveryCommand,
    RunInternalBotRunRecoveryCommandOptions,
)
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.board.BoardChatApi import get_project_chat_run
from langboard_shared.core.db import BaseDbModel, ChatContentModel, DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    ChatGraphApprovalRequest,
    ChatHistory,
    ChatSession,
    EditorGraphApprovalRequest,
    GraphApprovalRequest,
    InternalBotRun,
    Project,
    ProjectChatSession,
)
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from langboard_shared.domain.models.InternalBot import InternalBot, InternalBotType
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.ProjectAssignedInternalBot import ProjectAssignedInternalBot
from langboard_shared.domain.models.User import User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.GraphApprovalRequestService import GraphApprovalRequestService
from langboard_shared.domain.services.factory.InternalBotRunService import InternalBotRunService
from langboard_shared.domain.services.factory.ProjectService import ProjectService
from langboard_shared.helpers import MiddlewareHelper
from langboard_shared.infrastructure.repositories.factory.InternalBotRunRepository import InternalBotRunRepository
from langboard_shared.publishers import GraphApprovalPublisher
from langboard_shared.security import RoleSecurity
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import create_engine, func, select, update


@pytest.fixture
def run_repository(monkeypatch: MonkeyPatch) -> Iterator[InternalBotRunRepository]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for model in (
        ChatSession,
        ProjectChatSession,
        ChatHistory,
        InternalBotRun,
        GraphApprovalRequest,
        ChatGraphApprovalRequest,
        EditorGraphApprovalRequest,
    ):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    yield InternalBotRunRepository(lambda repository_type: None, lambda name: None)
    engine.dispose()


def make_run(request_key: str = "request-1", request_digest: str = "digest-1") -> InternalBotRun:
    return InternalBotRun(
        request_key=request_key,
        request_digest=request_digest,
        client_task_id="client-task-1",
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        kind=InternalBotRunKind.BoardChat,
        request_payload={"message": "hello"},
    )


def test_recovery_command_uses_internal_bot_run_service(monkeypatch: MonkeyPatch) -> None:
    service = Mock()
    service.internal_bot_run.recover_expired.return_value = []
    monkeypatch.setattr(DomainService, "use", lambda: nullcontext(service))

    RunInternalBotRunRecoveryCommand().execute(RunInternalBotRunRecoveryCommandOptions())

    service.internal_bot_run.recover_expired.assert_called_once_with()


def test_recovery_command_schedules_durable_board_chat_attachment_reconciliation(
    monkeypatch: MonkeyPatch,
) -> None:
    service = Mock()
    board_run = InternalBotRun.model_construct(id=SnowflakeID(1), kind=InternalBotRunKind.BoardChat)
    editor_run = InternalBotRun.model_construct(id=SnowflakeID(2), kind=InternalBotRunKind.EditorChat)
    service.internal_bot_run.recover_expired.return_value = [board_run, editor_run]
    schedule_reconciliation = Mock()
    monkeypatch.setattr(DomainService, "use", lambda: nullcontext(service))
    monkeypatch.setattr(
        RecoveryCommandModule,
        "schedule_board_chat_attachment_reconciliation",
        schedule_reconciliation,
    )

    RunInternalBotRunRecoveryCommand().execute(RunInternalBotRunRecoveryCommandOptions())

    schedule_reconciliation.assert_called_once_with(board_run.get_uid())


def test_accept_deduplicates_and_rejects_identity_reuse(run_repository: InternalBotRunRepository) -> None:
    first, accepted = run_repository.accept(make_run())
    assert accepted
    assert first.status == InternalBotRunStatus.Accepted

    duplicate, accepted = run_repository.accept(make_run())
    assert not accepted
    assert duplicate.id == first.id

    with pytest.raises(ValueError, match="different AI request"):
        run_repository.accept(make_run(request_digest="different"))


def test_accepted_editor_recovery_scan_includes_expired_unstarted_runs(
    run_repository: InternalBotRunRepository,
) -> None:
    first_candidate = make_run(request_key="editor-recovery-first")
    first_candidate.kind = InternalBotRunKind.EditorChat
    first_candidate.lease_expires_at = SafeDateTime.now() + timedelta(seconds=30)
    first, _ = run_repository.accept(first_candidate)

    second_candidate = make_run(request_key="editor-recovery-second")
    second_candidate.kind = InternalBotRunKind.EditorCopilot
    second_candidate.lease_expires_at = SafeDateTime.now() + timedelta(seconds=30)
    second, _ = run_repository.accept(second_candidate)

    board_candidate = make_run(request_key="editor-recovery-board")
    run_repository.accept(board_candidate)

    claimed_candidate = make_run(request_key="editor-recovery-claimed")
    claimed_candidate.kind = InternalBotRunKind.EditorChat
    claimed, _ = run_repository.accept(claimed_candidate)
    assert run_repository.claim(claimed.id, lease_seconds=30) is not None

    expired_candidate = make_run(request_key="editor-recovery-expired")
    expired_candidate.kind = InternalBotRunKind.EditorCopilot
    expired, _ = run_repository.accept(expired_candidate)
    with DbSession.use(readonly=False) as db:
        db.exec(
            update(InternalBotRun)
            .where(InternalBotRun.column("id") == expired.id)
            .values(lease_expires_at=SafeDateTime.now() - timedelta(seconds=1))
        )

    assert [run.id for run in run_repository.list_accepted_editor_runs(1)] == [first.id]
    assert [run.id for run in run_repository.list_accepted_editor_runs(1, first.id)] == [second.id]
    assert [run.id for run in run_repository.list_accepted_editor_runs(10, second.id)] == [expired.id]
    assert run_repository.mark_expired_uncertain(SafeDateTime.now(), 10) == []
    assert run_repository.claim(expired.id, lease_seconds=30) is not None


@pytest.mark.parametrize("kind", [InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot])
def test_editor_execution_and_status_reads_use_primary(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch, kind: InternalBotRunKind
) -> None:
    candidate = make_run(request_key=f"editor-primary-{kind.value}")
    candidate.kind = kind
    run, _ = run_repository.accept(candidate)

    def fail_replica_lookup() -> None:
        raise AssertionError("Editor execution and status must not read from a replica")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", fail_replica_lookup)
    accepted = run_repository.get_by_id(run.id)
    assert accepted is not None
    assert accepted.status == InternalBotRunStatus.Accepted

    cancelled = run_repository.cancel_editor(run.request_key, run.user_id, run.project_id, kind)
    assert cancelled is not None
    by_id = run_repository.get_by_id(run.id)
    by_task = run_repository.get_editor_run_by_request_key(run.request_key, run.user_id, run.project_id, kind)
    assert by_id is not None and by_id.status == InternalBotRunStatus.Cancelled
    assert by_task is not None and by_task.status == InternalBotRunStatus.Cancelled
    assert run_repository.get_editor_run_by_request_key(run.request_key, SnowflakeID(99), run.project_id, kind) is None
    assert run_repository.get_editor_run_by_request_key(run.request_key, run.user_id, SnowflakeID(99), kind) is None
    assert run_repository.get_by_id(SnowflakeID(999)) is None


@pytest.mark.parametrize("kind", [InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot])
def test_editor_graph_identity_and_finish_are_attempt_fenced(
    run_repository: InternalBotRunRepository, kind: InternalBotRunKind
) -> None:
    candidate = make_run(request_key=f"editor-{kind.value}")
    candidate.kind = kind
    run, accepted = run_repository.accept(candidate)
    assert accepted

    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    assert claimed.attempt == 1
    assert run_repository.claim(run.id, lease_seconds=30) is None
    assert not run_repository.set_editor_graph_identity(run.id, 0, "session", "thread")
    assert run_repository.set_editor_graph_identity(run.id, 1, "session", "thread")
    assert not run_repository.set_editor_graph_identity(run.id, 1, "session-2", "thread-2")

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.graph_session_id == "session"
    assert saved.graph_thread_id == "thread"
    assert not run_repository.finish(run.id, 0, InternalBotRunStatus.Completed, "Done")
    assert run_repository.finish(run.id, 1, InternalBotRunStatus.Completed, "Done")
    assert run_repository.finish(run.id, 1, InternalBotRunStatus.Completed, "Done")
    assert not run_repository.finish(run.id, 1, InternalBotRunStatus.Completed, "Changed")


@pytest.mark.parametrize("kind", [InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot])
def test_editor_cancel_is_owned_idempotent_and_blocks_late_execution(
    run_repository: InternalBotRunRepository, kind: InternalBotRunKind
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    user_id = SnowflakeID(7)
    project_id = SnowflakeID(13)
    scope_uid = SnowflakeID(29).to_short_code()
    run, accepted = service.accept_editor(
        kind=kind,
        task_id=task_id,
        user_id=user_id,
        project_id=project_id,
        internal_bot_id=SnowflakeID(11),
        scope_table="card",
        scope_uid=scope_uid,
        document_name=f"card:{scope_uid}:description",
        system="",
        messages=[{"role": "user", "content": "Draft"}] if kind == InternalBotRunKind.EditorChat else None,
        prompt="Continue this" if kind == InternalBotRunKind.EditorCopilot else None,
    )
    assert accepted
    assert service.cancel_editor(kind, task_id, SnowflakeID(8), project_id) is None
    assert service.cancel_editor(kind, task_id, user_id, SnowflakeID(14)) is None
    cancelled = service.cancel_editor(kind, task_id, user_id, project_id)
    assert cancelled is not None
    assert cancelled.id == run.id
    assert cancelled.status == InternalBotRunStatus.Cancelled
    assert service.cancel_editor(kind, task_id, user_id, project_id) is not None
    assert run_repository.claim(run.id, lease_seconds=30) is None

    other = InternalBotRunKind.EditorCopilot if kind == InternalBotRunKind.EditorChat else InternalBotRunKind.EditorChat
    assert service.cancel_editor(other, task_id, user_id, project_id) is None


@pytest.mark.parametrize("kind", [InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot])
def test_editor_cancel_routes_awaiting_approval_to_approval_service(kind: InternalBotRunKind) -> None:
    task_id = uuid4()
    user_id = SnowflakeID(7)
    project_id = SnowflakeID(13)
    run = InternalBotRun(
        id=SnowflakeID(17),
        request_key="editor-awaiting-approval",
        request_digest="digest",
        client_task_id=str(task_id),
        user_id=user_id,
        project_id=project_id,
        internal_bot_id=SnowflakeID(3),
        kind=kind,
        status=InternalBotRunStatus.AwaitingApproval,
        request_payload={"graph_interrupt": {"value": {"approval_uid": "approval-uid"}}},
    )
    repository = Mock(internal_bot_run=Mock())
    repository.internal_bot_run.get_editor_run_by_request_key.return_value = run
    project_service = Mock()
    project = object()
    project_service.get_by_id_like.return_value = project
    approval_service = Mock()
    approval_service.cancel_editor_run.return_value = run

    services = {
        ProjectService: project_service,
        GraphApprovalRequestService: approval_service,
    }
    service = InternalBotRunService(lambda service_type: services[service_type], lambda name: None, repository)

    assert service.cancel_editor(kind, task_id, user_id, project_id) is run
    project_service.get_by_id_like.assert_called_once_with(project_id)
    approval_service.cancel_editor_run.assert_called_once_with(run, project, reason="Editor AI run cancelled")
    repository.internal_bot_run.cancel_editor.assert_not_called()


@pytest.mark.parametrize("kind", [InternalBotRunKind.EditorChat, InternalBotRunKind.EditorCopilot])
def test_editor_accept_deduplicates_without_a_new_run_model(
    run_repository: InternalBotRunRepository, kind: InternalBotRunKind
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    scope_uid = SnowflakeID(29).to_short_code()
    messages = [{"role": "user", "content": "Draft"}] if kind == InternalBotRunKind.EditorChat else None
    prompt = "Continue this" if kind == InternalBotRunKind.EditorCopilot else None

    def accept(system: str) -> tuple[InternalBotRun, bool]:
        return service.accept_editor(
            kind=kind,
            task_id=task_id,
            user_id=SnowflakeID(7),
            project_id=SnowflakeID(13),
            internal_bot_id=SnowflakeID(11),
            scope_table="card",
            scope_uid=scope_uid,
            document_name=f"card:{scope_uid}:description",
            system=system,
            messages=messages,
            prompt=prompt,
        )

    first, accepted = accept("Editor context")

    assert accepted
    assert first.kind == kind
    assert first.status == InternalBotRunStatus.Accepted
    assert first.client_task_id == str(task_id)
    assert len(first.request_key) == len(first.request_digest) == 64
    assert first.lease_expires_at is not None

    duplicate, accepted = accept("Editor context")
    assert not accepted
    assert duplicate.id == first.id

    with pytest.raises(ValueError, match="different AI request"):
        accept("Different context")


def test_claim_and_terminal_transition_are_fenced(run_repository: InternalBotRunRepository) -> None:
    run, _ = run_repository.accept(make_run())
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    assert claimed.status == InternalBotRunStatus.Streaming
    assert claimed.attempt == 1
    assert claimed.lease_expires_at is not None
    assert run_repository.claim(run.id, lease_seconds=30) is None

    assert not run_repository.finish(run.id, 0, InternalBotRunStatus.Completed)
    assert run_repository.finish(run.id, 1, InternalBotRunStatus.Completed, output_text="response")
    assert run_repository.finish(run.id, 1, InternalBotRunStatus.Completed, output_text="response")
    assert not run_repository.finish(run.id, 1, InternalBotRunStatus.Failed)

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Completed
    assert saved.output_text == "response"
    assert saved.finished_at is not None
    assert saved.lease_expires_at is None


def test_finish_rejects_nonterminal_status(run_repository: InternalBotRunRepository) -> None:
    run, _ = run_repository.accept(make_run())
    with pytest.raises(ValueError, match="terminal status"):
        run_repository.finish(run.id, 0, InternalBotRunStatus.AwaitingApproval)


def test_expired_worker_becomes_uncertain_and_cannot_finish(run_repository: InternalBotRunRepository) -> None:
    run, _ = run_repository.accept(make_run())
    assert run_repository.claim(run.id, lease_seconds=30) is not None
    assert run_repository.mark_expired_uncertain(SafeDateTime.now(), 1) == []

    expired = run_repository.mark_expired_uncertain(SafeDateTime.now() + timedelta(seconds=31), 1)
    assert [item.id for item in expired] == [run.id]
    assert not run_repository.finish(run.id, 1, InternalBotRunStatus.Completed)

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Uncertain
    assert saved.error_message == "AI worker lease expired before a terminal result"


def test_expired_accepted_board_chat_remains_recoverable_if_start_never_runs(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, accepted, _, _, user_message = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    assert accepted
    assert run.lease_expires_at is not None
    assert run_repository.mark_expired_uncertain(run.lease_expires_at - timedelta(seconds=1), 1) == []

    assert run_repository.mark_expired_uncertain(run.lease_expires_at + timedelta(seconds=1), 1) == []
    assert [item.id for item in service.list_accepted_board_chat_runs(10)] == [run.id]
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None and claimed.attempt == 1

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Streaming
    assert saved.ai_chat_history_id is None
    with DbSession.use(readonly=False) as db:
        persisted_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == user_message.id)
        ).first()
    assert persisted_message is not None
    assert persisted_message.message.content == "Prepare the graph"


def test_accepted_board_chat_scan_includes_expired_unstarted_but_excludes_claimed_and_other_kinds(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))

    def accept_board_run() -> InternalBotRun:
        run, _, _, _, _ = service.accept_board_chat(
            task_id=uuid4(),
            user_id=SnowflakeID(10),
            project_id=SnowflakeID(20),
            internal_bot_id=SnowflakeID(30),
            project_chat_session_id=None,
            message="Prepare the graph",
            permission_level="read",
            scope_table="project",
            scope_uid=None,
        )
        return run

    ready = accept_board_run()
    claimed = accept_board_run()
    expired = accept_board_run()
    later = accept_board_run()
    assert run_repository.claim(claimed.id, lease_seconds=30) is not None
    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            update(InternalBotRun.__table__)
            .where(InternalBotRun.__table__.c.id == expired.id)
            .values(lease_expires_at=SafeDateTime.now() - timedelta(seconds=1))
        )
    other_kind = make_run(request_key="editor-run", request_digest="editor-run")
    other_kind.kind = InternalBotRunKind.EditorChat
    other_kind.lease_expires_at = SafeDateTime.now() + timedelta(seconds=30)
    run_repository.accept(other_kind)

    assert [run.id for run in service.list_accepted_board_chat_runs(10)] == [ready.id, expired.id, later.id]
    assert [run.id for run in service.list_accepted_board_chat_runs(1)] == [ready.id]
    assert [run.id for run in service.list_accepted_board_chat_runs(1, ready.id)] == [expired.id]
    assert [run.id for run in service.list_accepted_board_chat_runs(1, expired.id)] == [later.id]
    assert service.list_accepted_board_chat_runs(1, later.id) == []
    assert service.list_accepted_board_chat_runs(0) == []


def test_expired_board_chat_run_hides_its_empty_ai_placeholder(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=1)
    assert claimed is not None
    assert claimed.lease_expires_at is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None

    expired = run_repository.mark_expired_uncertain(claimed.lease_expires_at + timedelta(seconds=1), 1)
    assert [item.id for item in expired] == [run.id]
    assert not run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="late")
    with DbSession.use(readonly=False) as db:
        hidden = db.exec(
            SqlBuilder.select.table(ChatHistory, with_deleted=True).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert hidden is not None
    assert hidden.deleted_at is not None


def test_expired_board_chat_run_preserves_saved_partial_answer(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=1)
    assert claimed is not None
    assert claimed.lease_expires_at is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None

    with DbSession.use(readonly=False) as db:
        partial = db.exec(SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)).first()
        assert partial is not None
        partial.message = ChatContentModel(content="Partial answer")
        db.update(partial)

    expired = run_repository.mark_expired_uncertain(claimed.lease_expires_at + timedelta(seconds=1), 1)
    assert [item.id for item in expired] == [run.id]
    with DbSession.use(readonly=False) as db:
        saved = db.exec(SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)).first()
    assert saved is not None
    assert saved.message.content == "Partial answer"


def test_recover_expired_service_marks_only_elapsed_lease(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    expired, _ = run_repository.accept(make_run(request_key="expired"))
    active, _ = run_repository.accept(make_run(request_key="active"))
    expired_claim = run_repository.claim(expired.id, lease_seconds=30)
    active_claim = run_repository.claim(active.id, lease_seconds=30)
    assert expired_claim is not None and active_claim is not None

    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            update(InternalBotRun.__table__)
            .where(InternalBotRun.__table__.c.id == expired.id)
            .values(lease_expires_at=SafeDateTime.now() - timedelta(seconds=1))
        )

    recovered = service.recover_expired(limit=10)
    assert [run.id for run in recovered] == [expired.id]
    assert service.recover_expired(limit=10) == []
    expired_saved = run_repository.get_by_id(expired.id)
    active_saved = run_repository.get_by_id(active.id)
    assert expired_saved is not None and expired_saved.status == InternalBotRunStatus.Uncertain
    assert active_saved is not None and active_saved.status == InternalBotRunStatus.Streaming


def test_active_attempt_can_renew_lease_but_stale_or_terminal_attempt_cannot(
    run_repository: InternalBotRunRepository,
) -> None:
    run, _ = run_repository.accept(make_run())
    claimed = run_repository.claim(run.id, lease_seconds=1)
    assert claimed is not None
    assert claimed.lease_expires_at is not None
    original_expiry = claimed.lease_expires_at

    assert not run_repository.renew_lease(run.id, 0, lease_seconds=30)
    assert run_repository.renew_lease(run.id, claimed.attempt, lease_seconds=30)
    renewed = run_repository.get_by_id(run.id)
    assert renewed is not None
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > original_expiry.replace(tzinfo=None)
    assert run_repository.mark_expired_uncertain(original_expiry + timedelta(seconds=1), 1) == []

    assert run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed)
    assert not run_repository.renew_lease(run.id, claimed.attempt, lease_seconds=30)
    with pytest.raises(ValueError, match="lease must be positive"):
        run_repository.renew_lease(run.id, claimed.attempt, lease_seconds=0)


def test_board_chat_acceptance_is_idempotent_without_storing_credentials(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()

    def accept(
        message: str = "Summarize the card", user_id: SnowflakeID = SnowflakeID(10)
    ) -> tuple[InternalBotRun, bool, ChatSession, ProjectChatSession, ChatHistory]:
        return service.accept_board_chat(
            task_id=task_id,
            user_id=user_id,
            project_id=SnowflakeID(20),
            internal_bot_id=SnowflakeID(30),
            project_chat_session_id=None,
            message=message,
            permission_level="read",
            scope_table="card",
            scope_uid="card-uid",
        )

    first, accepted, chat_session, project_session, user_message = accept()
    assert accepted
    assert first.chat_session_id == chat_session.id
    assert first.chat_history_id == user_message.id
    assert project_session.project_id == SnowflakeID(20)
    assert user_message.message.content == "Summarize the card"
    persisted = run_repository.get_by_id(first.id)
    assert persisted is not None
    assert persisted.chat_session_id == chat_session.id
    assert persisted.chat_history_id == user_message.id

    second, accepted, duplicate_session, duplicate_project_session, duplicate_message = accept()
    assert not accepted
    assert first.id == second.id
    assert chat_session.id == duplicate_session.id
    assert project_session.id == duplicate_project_session.id
    assert user_message.id == duplicate_message.id
    assert first.request_payload == {"message": "Summarize the card", "api_permission_level": "read"}
    assert len(first.request_key) == len(first.request_digest) == 64

    with pytest.raises(ValueError, match="different AI request"):
        accept(message="Different instruction")

    other_user, accepted, _, _, _ = accept(user_id=SnowflakeID(11))
    assert accepted
    assert other_user.id != first.id

    same_run, accepted, _, _, _ = service.accept_board_chat(
        task_id=task_id,
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=project_session.id,
        message="Summarize the card",
        permission_level="read",
        scope_table="card",
        scope_uid="card-uid",
    )
    assert not accepted
    assert same_run.id == first.id

    with pytest.raises(ValueError, match="different chat session"):
        service.accept_board_chat(
            task_id=task_id,
            user_id=SnowflakeID(10),
            project_id=SnowflakeID(20),
            internal_bot_id=SnowflakeID(30),
            project_chat_session_id=SnowflakeID(999),
            message="Summarize the card",
            permission_level="read",
            scope_table="card",
            scope_uid="card-uid",
        )

    engine = DbEngine.get_main_engine()
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChatSession.__table__)) == 2
        assert connection.scalar(select(func.count()).select_from(ProjectChatSession.__table__)) == 2
        assert connection.scalar(select(func.count()).select_from(ChatHistory.__table__)) == 2
        last_messaged_at = connection.scalar(
            select(ChatSession.__table__.c.last_messaged_at).where(ChatSession.__table__.c.id == chat_session.id)
        )
    assert last_messaged_at is not None
    assert last_messaged_at.replace(tzinfo=timezone.utc) == user_message.created_at


def test_board_chat_cancel_is_owned_idempotent_and_blocks_late_start(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    run, _, _, _, user_message = service.accept_board_chat(
        task_id=task_id,
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )

    assert service.cancel_board_chat(task_id, SnowflakeID(11), SnowflakeID(20)) is None
    assert service.cancel_board_chat(task_id, SnowflakeID(10), SnowflakeID(21)) is None
    cancelled = service.cancel_board_chat(task_id, SnowflakeID(10), SnowflakeID(20))
    assert cancelled is not None
    assert cancelled.id == run.id
    assert cancelled.status == InternalBotRunStatus.Cancelled
    assert cancelled.finished_at is not None
    assert cancelled.lease_expires_at is None
    assert service.cancel_board_chat(task_id, SnowflakeID(10), SnowflakeID(20)) is not None
    assert run_repository.claim(run.id, lease_seconds=30) is None

    with DbSession.use(readonly=True) as db:
        saved_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == user_message.id)
        ).first()
    assert saved_message is not None
    assert saved_message.message.content == "Prepare the graph"


def test_board_chat_cancel_hides_empty_response_and_rejects_late_finish(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    run, _, _, _, _ = service.accept_board_chat(
        task_id=task_id,
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None

    cancelled = service.cancel_board_chat(task_id, SnowflakeID(10), SnowflakeID(20))
    assert cancelled is not None
    assert cancelled.status == InternalBotRunStatus.Cancelled
    assert not run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="late")
    assert not run_repository.renew_lease(run.id, claimed.attempt, lease_seconds=30)

    with DbSession.use(readonly=False) as db:
        persisted = db.exec(
            SqlBuilder.select.table(ChatHistory, with_deleted=True).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert persisted is not None
    assert persisted.deleted_at is not None


def test_board_chat_cancel_cannot_rewrite_completed_result(run_repository: InternalBotRunRepository) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    run, _, _, _, _ = service.accept_board_chat(
        task_id=task_id,
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    assert run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread") is not None
    assert run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="done")

    assert service.cancel_board_chat(task_id, SnowflakeID(10), SnowflakeID(20)) is None
    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Completed
    assert saved.output_text == "done"


def test_board_chat_context_uses_primary_and_requires_bound_user_message(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, chat_session, project_session, user_message = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the run",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )

    def fail_replica_lookup() -> None:
        raise AssertionError("Execution context must not read from a replica")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", fail_replica_lookup)
    context = run_repository.get_board_chat_context(run.id)
    assert context is not None
    assert context[0].id == run.id
    assert context[1].id == project_session.id
    assert context[2].id == user_message.id

    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            update(ChatHistory.__table__).where(ChatHistory.__table__.c.id == user_message.id).values(is_received=True)
        )

    assert run_repository.get_board_chat_context(run.id) is None
    assert run_repository.get_board_chat_context(SnowflakeID(999)) is None

    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            update(ChatHistory.__table__).where(ChatHistory.__table__.c.id == user_message.id).values(is_received=False)
        )
        connection.execute(
            update(ChatSession.__table__).where(ChatSession.__table__.c.id == chat_session.id).values(user_id=99)
        )

    assert run_repository.get_board_chat_context(run.id) is None


def test_owned_board_chat_status_reconciles_terminal_messages(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    task_id = uuid4()
    run, _, _, project_session, user_message = service.accept_board_chat(
        task_id=task_id,
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the run",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )

    def fail_replica_lookup() -> None:
        raise AssertionError("Run status must not read from a replica")

    monkeypatch.setattr(DbEngine, "get_readonly_engine", fail_replica_lookup)
    accepted = service.get_owned_board_chat_status(task_id, SnowflakeID(10), SnowflakeID(20))
    assert accepted is not None
    assert accepted[0].status == InternalBotRunStatus.Accepted
    assert accepted[1].id == project_session.id
    assert accepted[2].id == user_message.id
    assert accepted[3] is None
    api_service = Mock(internal_bot_run=service)
    api_service.project.get_by_id_like.return_value = Project.model_construct(id=SnowflakeID(20))
    payload = orjson.loads(
        get_project_chat_run("project-uid", task_id, User.model_construct(id=SnowflakeID(10)), api_service).body
    )
    assert payload["status"] == "accepted"
    assert payload["session_uid"] == project_session.get_uid()
    assert payload["user_message"]["uid"] == user_message.get_uid()
    assert payload["ai_message"] is None
    assert payload["ai_message_uid"] is None
    assert not {"request_payload", "request_digest", "request_key", "error_message"} & payload.keys()
    assert service.get_owned_board_chat_status(task_id, SnowflakeID(11), SnowflakeID(20)) is None
    assert service.get_owned_board_chat_status(task_id, SnowflakeID(10), SnowflakeID(21)) is None
    assert service.get_owned_board_chat_status(uuid4(), SnowflakeID(10), SnowflakeID(20)) is None

    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None
    assert run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="Done")
    completed = service.get_owned_board_chat_status(task_id, SnowflakeID(10), SnowflakeID(20))
    assert completed is not None
    assert completed[0].status == InternalBotRunStatus.Completed
    assert completed[3] is not None
    assert completed[3].id == ai_message.id
    assert completed[3].message.content == "Done"
    completed_payload = orjson.loads(
        get_project_chat_run("project-uid", task_id, User.model_construct(id=SnowflakeID(10)), api_service).body
    )
    assert completed_payload["ai_message"]["message"]["content"] == "Done"
    assert completed_payload["ai_message_uid"] == ai_message.get_uid()

    with DbEngine.get_main_engine().begin() as connection:
        connection.execute(
            update(ChatHistory.__table__)
            .where(ChatHistory.__table__.c.id == ai_message.id)
            .values(deleted_at=SafeDateTime.now())
        )
    hidden = service.get_owned_board_chat_status(task_id, SnowflakeID(10), SnowflakeID(20))
    assert hidden is not None
    assert hidden[0].ai_chat_history_id == ai_message.id
    assert hidden[3] is None
    hidden_payload = orjson.loads(
        get_project_chat_run("project-uid", task_id, User.model_construct(id=SnowflakeID(10)), api_service).body
    )
    assert hidden_payload["ai_message"] is None
    assert hidden_payload["ai_message_uid"] == ai_message.get_uid()


def test_board_chat_status_http_requires_auth_and_project_read(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(id=SnowflakeID(10), email="member@example.invalid", is_admin=False)
    service = Mock()
    service.project.get_by_id_like.return_value = Project.model_construct(id=SnowflakeID(20))
    service.internal_bot_run.get_owned_board_chat_status.return_value = None
    authorized = {"value": False}

    def authenticate(scope: dict[str, Any]) -> User | int:
        if not any(name == b"authorization" for name, _ in scope["headers"]):
            return 401
        scope["auth"] = user
        return user

    monkeypatch.setattr(MiddlewareHelper, "validate_auth", authenticate)
    monkeypatch.setattr(RoleSecurity, "is_authorized", lambda *args: authorized["value"])
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is get_project_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service

    client = TestClient(app)
    task_id = uuid4()
    path = f"/board/project-uid/chat/run/{task_id}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer token"}).status_code == 403
    service.internal_bot_run.get_owned_board_chat_status.assert_not_called()

    authorized["value"] = True
    assert client.get(path, headers={"Authorization": "Bearer token"}).status_code == 404
    service.internal_bot_run.get_owned_board_chat_status.assert_called_once_with(task_id, user.id, SnowflakeID(20))


def test_board_chat_start_claims_once_and_persists_graph_identity(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, project_session, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="edit",
        scope_table="project",
        scope_uid=None,
    )
    bot = InternalBot.model_construct(
        id=SnowflakeID(30),
        bot_type=InternalBotType.ProjectChat,
        platform=BotPlatform.Default,
        platform_running_type=BotPlatformRunningType.Default,
        value="{}",
    )
    user = User.model_construct(id=SnowflakeID(10))
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(20), internal_bot_id=SnowflakeID(30), use_default_prompt=True
    )

    started = service.start_board_chat(
        run.id,
        bot,
        user,
        assignment,
        project_session,
        scope_context=None,
        active_collaborative_documents=[],
        lease_seconds=30,
    )
    assert started is not None
    claimed, graph_request, ai_message = started
    assert claimed.status == InternalBotRunStatus.Streaming
    assert claimed.attempt == 1
    assert graph_request["session_id"] == project_session.get_uid()
    assert graph_request["input_value"] == "Prepare the graph"
    assert ai_message.is_received
    assert ai_message.chat_session_id == project_session.chat_session_id
    assert ai_message.message.content == ""

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.graph_session_id == graph_request["session_id"]
    assert saved.graph_thread_id == graph_request["thread_id"]
    assert saved.ai_chat_history_id == ai_message.id
    assert not run_repository.set_graph_identity(run.id, 0, "wrong", "wrong")
    assert not run_repository.set_graph_identity(SnowflakeID(999), 1, "wrong", "wrong")
    assert run_repository.set_graph_identity(run.id, 1, "duplicate", "duplicate") is None
    assert (
        service.start_board_chat(
            run.id,
            bot,
            user,
            assignment,
            project_session,
            scope_context=None,
            active_collaborative_documents=[],
            lease_seconds=30,
        )
        is None
    )
    with DbEngine.get_main_engine().connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChatHistory.__table__)) == 2

    another_run, _, _, another_session, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Second graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    monkeypatch.setattr(run_repository, "set_graph_identity", lambda *args: None)
    with pytest.raises(RuntimeError, match="Graph identity fence"):
        service.start_board_chat(
            another_run.id,
            bot,
            user,
            assignment,
            another_session,
            scope_context=None,
            active_collaborative_documents=[],
            lease_seconds=30,
        )
    failed = run_repository.get_by_id(another_run.id)
    assert failed is not None
    assert failed.status == InternalBotRunStatus.Failed
    assert failed.ai_chat_history_id is None


def test_langflow_board_chat_claim_and_finish_use_the_existing_run_and_messages(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, accepted, _, project_session, user_message = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Summarize this project",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    assert accepted
    bot = InternalBot.model_construct(
        id=SnowflakeID(30),
        bot_type=InternalBotType.ProjectChat,
        platform=BotPlatform.Langflow,
        platform_running_type=BotPlatformRunningType.Endpoint,
        api_url="https://langflow.example.test",
        api_key="server-only-key",
        value="/api/v1/run/flow",
    )
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(20), internal_bot_id=SnowflakeID(30), use_default_prompt=True
    )

    started = service.start_board_chat(
        run.id,
        bot,
        User.model_construct(id=SnowflakeID(10)),
        assignment,
        project_session,
        scope_context=None,
        active_collaborative_documents=[],
        lease_seconds=30,
    )
    assert started is not None
    claimed, request, ai_message = started
    assert claimed.attempt == 1
    assert request["request_body"]["input_value"] == "Summarize this project"
    assert request["api_key"] == "server-only-key"
    assert ai_message.chat_session_id == user_message.chat_session_id
    assert (
        service.start_board_chat(
            run.id,
            bot,
            User.model_construct(id=SnowflakeID(10)),
            assignment,
            project_session,
            scope_context=None,
            active_collaborative_documents=[],
            lease_seconds=30,
        )
        is None
    )

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.graph_session_id == request["session_id"]
    assert saved.graph_thread_id == request["thread_id"]
    assert service.finish_board_chat(run.id, claimed.attempt, InternalBotRunStatus.Completed, "Final answer", None)
    completed = run_repository.get_by_id(run.id)
    assert completed is not None
    assert completed.status == InternalBotRunStatus.Completed


def test_board_chat_start_marks_invalid_graph_configuration_failed(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, project_session, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    bot = InternalBot.model_construct(
        id=SnowflakeID(30),
        bot_type=InternalBotType.ProjectChat,
        platform=BotPlatform.Default,
        platform_running_type=BotPlatformRunningType.Default,
        value="{invalid json",
    )
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(20), internal_bot_id=SnowflakeID(30), use_default_prompt=True
    )

    with pytest.raises(ValueError, match="settings are invalid"):
        service.start_board_chat(
            run.id,
            bot,
            User.model_construct(id=SnowflakeID(10)),
            assignment,
            project_session,
            scope_context=None,
            active_collaborative_documents=[],
            lease_seconds=30,
        )

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Failed
    assert saved.attempt == 1
    assert saved.graph_session_id is None
    assert saved.ai_chat_history_id is None


def test_graph_identity_rolls_back_ai_message_if_session_update_fails(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    original_update = DbSession.update

    def fail_session_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, ChatSession):
            raise RuntimeError("Simulated chat session update failure")
        original_update(db, model)

    monkeypatch.setattr(DbSession, "update", fail_session_update)
    with pytest.raises(RuntimeError, match="Simulated chat session update failure"):
        run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.ai_chat_history_id is None
    assert saved.graph_thread_id is None
    with DbEngine.get_main_engine().connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChatHistory.__table__)) == 1


@pytest.mark.parametrize(
    ("status", "output_text", "visible"),
    [
        (InternalBotRunStatus.Completed, "Graph answer", True),
        (InternalBotRunStatus.Failed, "Partial answer", False),
        (InternalBotRunStatus.Cancelled, "", False),
        (InternalBotRunStatus.Cancelled, "Partial answer", True),
    ],
)
def test_board_chat_finish_persists_message_and_state_once(
    run_repository: InternalBotRunRepository,
    status: InternalBotRunStatus,
    output_text: str,
    visible: bool,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None

    assert run_repository.finish(run.id, claimed.attempt, status, output_text=output_text)
    assert run_repository.finish(run.id, claimed.attempt, status, output_text=output_text)
    assert not run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="duplicate")
    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == status
    assert saved.output_text == output_text
    assert saved.ai_chat_history_id == ai_message.id
    assert saved.finished_at is not None

    with DbSession.use(readonly=False) as db:
        persisted = db.exec(
            SqlBuilder.select.table(ChatHistory, with_deleted=True).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert persisted is not None
    assert (persisted.deleted_at is None) == visible
    assert persisted.message.content == (output_text if visible else "")


def test_board_chat_run_can_finish_after_user_message_is_deleted(
    run_repository: InternalBotRunRepository,
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, user_message = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None

    with DbSession.use(readonly=False) as db:
        original = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == user_message.id)
        ).first()
        assert original is not None
        db.delete(original)

    assert run_repository.get_board_chat_context(run.id) is None
    assert run_repository.get_board_chat_run(run.id) is not None
    assert run_repository.renew_lease(run.id, claimed.attempt, lease_seconds=30)
    assert run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="Graph answer")

    with DbSession.use(readonly=False) as db:
        saved = db.exec(SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)).first()
    assert saved is not None
    assert saved.message.content == "Graph answer"


def test_board_chat_finish_rolls_back_message_on_run_update_failure(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None
    original_update = DbSession.update

    def fail_run_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, InternalBotRun):
            raise RuntimeError("Simulated AI run update failure")
        original_update(db, model)

    monkeypatch.setattr(DbSession, "update", fail_run_update)
    with pytest.raises(RuntimeError, match="Simulated AI run update failure"):
        run_repository.finish(run.id, claimed.attempt, InternalBotRunStatus.Completed, output_text="Graph answer")

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Streaming
    with DbSession.use(readonly=False) as db:
        persisted = db.exec(
            SqlBuilder.select.table(ChatHistory, with_deleted=True).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert persisted is not None
    assert persisted.message.content == ""


def test_board_chat_acceptance_rolls_back_every_record_on_message_failure(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    original_insert = DbSession.insert

    def fail_on_history(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, ChatHistory):
            raise RuntimeError("Simulated message storage failure")
        original_insert(db, model)

    monkeypatch.setattr(DbSession, "insert", fail_on_history)
    with pytest.raises(RuntimeError, match="Simulated message storage failure"):
        service.accept_board_chat(
            task_id=uuid4(),
            user_id=SnowflakeID(10),
            project_id=SnowflakeID(20),
            internal_bot_id=SnowflakeID(30),
            project_chat_session_id=None,
            message="hello",
            permission_level="read",
            scope_table="project",
            scope_uid=None,
        )

    engine = DbEngine.get_main_engine()
    with engine.connect() as connection:
        for model in (InternalBotRun, ChatSession, ProjectChatSession, ChatHistory):
            assert connection.scalar(select(func.count()).select_from(model.__table__)) == 0


def test_board_chat_acceptance_uses_existing_session_in_one_transaction(
    run_repository: InternalBotRunRepository,
) -> None:
    with DbSession.use(readonly=False) as db:
        chat_session = ChatSession(user_id=SnowflakeID(10), title="Existing", api_permission_level="read")
        db.insert(chat_session)
        project_session = ProjectChatSession(chat_session_id=chat_session.id, project_id=SnowflakeID(20))
        db.insert(project_session)

    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, accepted, same_session, project_session, user_message = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=project_session.id,
        message="Continue here",
        permission_level="edit",
        scope_table="project",
        scope_uid=None,
    )

    assert accepted
    assert run.chat_session_id == chat_session.id == same_session.id
    assert project_session.chat_session_id == chat_session.id
    assert user_message.chat_session_id == chat_session.id
    engine = DbEngine.get_main_engine()
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ChatSession.__table__)) == 1
        assert connection.scalar(select(ChatSession.__table__.c.api_permission_level)) == "edit"


def test_board_chat_acceptance_rejects_foreign_existing_session(
    run_repository: InternalBotRunRepository,
) -> None:
    with DbSession.use(readonly=False) as db:
        chat_session = ChatSession(user_id=SnowflakeID(99), title="Other")
        db.insert(chat_session)
        project_session = ProjectChatSession(chat_session_id=chat_session.id, project_id=SnowflakeID(20))
        db.insert(project_session)

    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    with pytest.raises(PermissionError, match="not assigned"):
        service.accept_board_chat(
            task_id=uuid4(),
            user_id=SnowflakeID(10),
            project_id=SnowflakeID(20),
            internal_bot_id=SnowflakeID(30),
            project_chat_session_id=project_session.id,
            message="Unauthorized",
            permission_level="read",
            scope_table="project",
            scope_uid=None,
        )

    engine = DbEngine.get_main_engine()
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(InternalBotRun.__table__)) == 0
        assert connection.scalar(select(func.count()).select_from(ChatHistory.__table__)) == 0


def _claimed_board_chat(run_repository: InternalBotRunRepository) -> tuple[InternalBotRun, ChatHistory]:
    service = InternalBotRunService(lambda service_type: None, lambda name: None, Mock(internal_bot_run=run_repository))
    run, _, _, _, _ = service.accept_board_chat(
        task_id=uuid4(),
        user_id=SnowflakeID(10),
        project_id=SnowflakeID(20),
        internal_bot_id=SnowflakeID(30),
        project_chat_session_id=None,
        message="Prepare the graph",
        permission_level="read",
        scope_table="project",
        scope_uid=None,
    )
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    ai_message = run_repository.set_graph_identity(run.id, claimed.attempt, "session", "thread")
    assert ai_message is not None
    prepared = run_repository.get_board_chat_run(run.id)
    assert prepared is not None
    return prepared, ai_message


def _approval_interrupt(project_uid: str) -> dict[str, Any]:
    return {
        "id": "graph-interrupt-1",
        "value": {
            "type": "approval_request",
            "origin_type": "chat",
            "scope_table": "project",
            "scope_uid": project_uid,
            "thread_id": "thread",
            "session_id": "session",
            "permission": "edit",
            "preview": {"title": "Approval required"},
            "request_payload": {"api_name": "update_card"},
        },
    }


def _claimed_editor(run_repository: InternalBotRunRepository) -> InternalBotRun:
    scope_uid = SnowflakeID(42).to_short_code()
    candidate = make_run(request_key="editor-approval")
    candidate.kind = InternalBotRunKind.EditorChat
    candidate.scope_table = "card"
    candidate.scope_uid = scope_uid
    candidate.request_payload = {"document_name": f"card:{scope_uid}:description", "system": ""}
    run, accepted = run_repository.accept(candidate)
    assert accepted
    claimed = run_repository.claim(run.id, lease_seconds=30)
    assert claimed is not None
    assert run_repository.set_editor_graph_identity(run.id, claimed.attempt, "editor-session", "editor-thread")
    prepared = run_repository.get_by_id(run.id)
    assert prepared is not None
    return prepared


def _editor_approval_interrupt(run: InternalBotRun) -> dict[str, Any]:
    return {
        "id": "editor-graph-interrupt",
        "value": {
            "type": "approval_request",
            "origin_type": "editor",
            "scope_table": run.scope_table,
            "scope_uid": run.scope_uid,
            "document_name": run.request_payload["document_name"],
            "thread_id": run.graph_thread_id,
            "session_id": run.graph_session_id,
            "permission": "edit",
            "preview": {"title": "Approval required"},
            "request_payload": {"api_name": "update_card"},
        },
    }


def test_editor_pause_persists_one_owned_approval_and_is_idempotent(
    run_repository: InternalBotRunRepository,
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_editor_interrupt(run, interrupt)

    first = run_repository.pause_editor(run.id, run.attempt, "Partial answer", interrupt, approval)
    assert first is not None
    saved_interrupt, newly_applied = first
    assert newly_applied
    assert saved_interrupt["value"]["approval_uid"] == approval.get_uid()
    assert run_repository.pause_editor(run.id, run.attempt, "Partial answer", interrupt, approval) == (
        saved_interrupt,
        False,
    )
    assert run_repository.pause_editor(run.id, run.attempt - 1, "Partial answer", interrupt, approval) is None
    assert run_repository.pause_editor(run.id, run.attempt, "Changed", interrupt, approval) is None
    assert run_repository.get_editor_run_by_approval(approval.id) is not None
    assert not run_repository.finish(run.id, run.attempt, InternalBotRunStatus.Completed)

    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.AwaitingApproval
    assert saved.lease_expires_at is None
    with DbEngine.get_main_engine().connect() as connection:
        assert connection.scalar(select(func.count()).select_from(GraphApprovalRequest.__table__)) == 1
        assert connection.scalar(select(func.count()).select_from(EditorGraphApprovalRequest.__table__)) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin_type", "chat"),
        ("scope_table", "project_wiki"),
        ("scope_uid", "foreign-card"),
        ("document_name", "card:foreign:description"),
        ("thread_id", "foreign-thread"),
        ("session_id", "foreign-session"),
        ("request_payload", None),
    ],
)
def test_editor_pause_rejects_foreign_interrupt(
    run_repository: InternalBotRunRepository, field: str, value: Any
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    interrupt["value"][field] = value
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    with pytest.raises(ValueError, match="does not belong"):
        approval_service.prepare_editor_interrupt(run, interrupt)


def test_editor_pause_rolls_back_approval_with_run_update(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_editor_interrupt(run, interrupt)
    original_update = DbSession.update

    def fail_run_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, InternalBotRun):
            raise RuntimeError("Simulated editor pause failure")
        original_update(db, model)

    monkeypatch.setattr(DbSession, "update", fail_run_update)
    with pytest.raises(RuntimeError, match="Simulated editor pause failure"):
        run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval)

    saved = run_repository.get_by_id(run.id)
    assert saved is not None and saved.status == InternalBotRunStatus.Streaming
    with DbEngine.get_main_engine().connect() as connection:
        assert connection.scalar(select(func.count()).select_from(GraphApprovalRequest.__table__)) == 0
        assert connection.scalar(select(func.count()).select_from(EditorGraphApprovalRequest.__table__)) == 0


def test_editor_approval_expiry_closes_run_once(run_repository: InternalBotRunRepository) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval) is not None

    resolved = run_repository.close_editor_approval(approval.id, GraphApprovalStatus.Expired, "Approval expired")
    assert resolved is not None and resolved.status == GraphApprovalStatus.Expired
    assert run_repository.close_editor_approval(approval.id, GraphApprovalStatus.Expired, "Approval expired") is None
    assert run_repository.get_editor_run_by_approval(approval.id) is not None
    saved = run_repository.get_by_id(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.Failed
    assert saved.request_payload["graph_interrupt"]["value"]["status"] == "expired"


def test_durable_editor_approval_cannot_use_legacy_graph_resume(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval) is not None
    with DbSession.use(readonly=False) as db:
        saved_approval = db.exec(
            SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval.id)
        ).first()
    assert saved_approval is not None

    repository = Mock(internal_bot_run=run_repository)
    repository.graph_approval_request.get_by_id_like.return_value = saved_approval
    repository.graph_approval_request.get_expired_pending.return_value = [saved_approval]
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    graph_resume = Mock(side_effect=AssertionError("Legacy Graph resume was called"))
    checkpoint_cleanup = Mock()
    monkeypatch.setattr(GraphApprovalRequestService, "_GraphApprovalRequestService__resume_graph", graph_resume)
    monkeypatch.setattr(
        GraphApprovalRequestService, "_GraphApprovalRequestService__acknowledge_graph", checkpoint_cleanup
    )
    monkeypatch.setattr(service, "_GraphApprovalRequestService__get_project", lambda _approval: None)

    user = User.model_construct(id=run.user_id, email="editor@example.invalid")
    assert service.approve(approval.get_uid(), user) is None
    assert service.reject(approval.get_uid(), user) is None
    graph_resume.assert_not_called()
    assert service.expire_pending() == [saved_approval]
    graph_resume.assert_not_called()
    checkpoint_cleanup.assert_called_once()
    saved = run_repository.get_by_id(run.id)
    assert saved is not None and saved.status == InternalBotRunStatus.Failed


def test_editor_resume_claims_once_with_matching_approval(run_repository: InternalBotRunRepository) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval) is not None

    decision = {"approved": True, "rejected": False}
    claimed = run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(99), decision, 30)
    assert claimed is not None
    assert claimed.status == InternalBotRunStatus.Resuming
    assert claimed.attempt == run.attempt + 1
    assert claimed.request_payload["resume"] == decision
    assert claimed.request_payload["resume_actor_uid"] == SnowflakeID(99).to_short_code()
    assert "app_api_token" not in claimed.request_payload
    assert run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(99), decision, 30) is None
    assert run_repository.close_editor_approval(approval.id, GraphApprovalStatus.Expired, "Expired") is None


def test_editor_resume_failure_expires_pending_approval_once(
    run_repository: InternalBotRunRepository,
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "Partial", interrupt, approval) is not None
    claimed = run_repository.claim_editor_resume(
        approval.id,
        run.project_id,
        SnowflakeID(99),
        {"approved": True, "rejected": False},
        30,
    )
    assert claimed is not None

    result = run_repository.fail_editor_resume(
        claimed.id,
        claimed.attempt,
        "Editor AI scope access was revoked",
    )

    assert result is not None and result.newly_applied
    assert result.run.status == InternalBotRunStatus.Failed
    assert result.run.error_message == "Editor AI scope access was revoked"
    assert result.run.lease_expires_at is None
    assert result.expired_approval is not None
    assert result.expired_approval.status == GraphApprovalStatus.Expired
    assert result.run.request_payload["graph_interrupt"]["value"]["status"] == "expired"
    assert result.run.request_payload["resume_failure"] == {
        "attempt": claimed.attempt,
        "approval_uid": approval.get_uid(),
    }

    duplicate = run_repository.fail_editor_resume(
        claimed.id,
        claimed.attempt,
        "Editor AI scope access was revoked",
    )
    assert duplicate == (result.run, None, False)
    assert run_repository.complete_editor_resume(claimed.id, claimed.attempt, "late", None, None) is None


def test_editor_resume_claim_rejects_foreign_project_expiry_and_invalid_decisions(
    run_repository: InternalBotRunRepository,
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval) is not None

    approved = {"approved": True, "rejected": False}
    assert run_repository.claim_editor_resume(approval.id, SnowflakeID(99), SnowflakeID(1), approved, 30) is None
    for decision in (
        {"approved": False, "rejected": False},
        {"approved": True, "rejected": True},
        {"approved": True, "rejected": False, "app_api_token": "must-not-persist"},
    ):
        with pytest.raises(ValueError, match="Exactly one"):
            run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(1), decision, 30)
    with pytest.raises(ValueError, match="lease must be positive"):
        run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(1), approved, 0)

    with DbSession.use(readonly=False) as db:
        db.exec(
            update(GraphApprovalRequest)
            .where(GraphApprovalRequest.column("id") == approval.id)
            .values(expires_at=SafeDateTime.now() - timedelta(seconds=1))
        )
    assert run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(1), approved, 30) is None
    saved = run_repository.get_by_id(run.id)
    assert saved is not None and saved.status == InternalBotRunStatus.AwaitingApproval


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ({"approved": True, "rejected": False}, GraphApprovalStatus.Approved),
        ({"approved": False, "rejected": True, "reason": "Not allowed"}, GraphApprovalStatus.Rejected),
    ],
)
def test_editor_resume_result_resolves_approval_and_run_once(
    run_repository: InternalBotRunRepository, decision: dict[str, bool | str], expected_status: GraphApprovalStatus
) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "Partial", interrupt, approval) is not None
    claimed = run_repository.claim_editor_resume(approval.id, run.project_id, SnowflakeID(99), decision, 30)
    assert claimed is not None

    result = run_repository.complete_editor_resume(claimed.id, claimed.attempt, "Finished", None, None)
    assert result is not None and result.newly_applied
    assert result.resolved_approval is not None
    assert result.resolved_approval.status == expected_status
    assert result.resolved_approval.resolved_by_user_id == SnowflakeID(99)
    assert result.requested_approval is None
    assert result.run.status == InternalBotRunStatus.Completed
    assert result.run.output_text == "Finished"
    assert result.run.request_payload["graph_interrupt"] is None
    assert result.run.request_payload["resolved_interrupt"]["value"]["status"] == expected_status.value
    assert run_repository.complete_editor_resume(claimed.id, claimed.attempt, "Finished", None, None) == (
        result.run,
        None,
        None,
        False,
    )
    assert run_repository.complete_editor_resume(claimed.id, claimed.attempt, "Different", None, None) is None
    assert run_repository.complete_editor_resume(claimed.id, claimed.attempt - 1, "Finished", None, None) is None


def test_editor_resume_can_pause_again_with_one_new_approval(run_repository: InternalBotRunRepository) -> None:
    run = _claimed_editor(run_repository)
    interrupt = _editor_approval_interrupt(run)
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_editor_interrupt(run, interrupt)
    assert run_repository.pause_editor(run.id, run.attempt, "", interrupt, approval) is not None
    claimed = run_repository.claim_editor_resume(
        approval.id, run.project_id, SnowflakeID(99), {"approved": True, "rejected": False}, 30
    )
    assert claimed is not None

    next_interrupt = _editor_approval_interrupt(claimed)
    next_interrupt["id"] = "next-editor-interrupt"
    next_approval = prepared.prepare_editor_interrupt(claimed, next_interrupt)
    result = run_repository.complete_editor_resume(
        claimed.id, claimed.attempt, "Continue", next_interrupt, next_approval
    )
    assert result is not None and result.newly_applied
    assert result.run.status == InternalBotRunStatus.AwaitingApproval
    assert result.resolved_approval is not None and result.resolved_approval.status == GraphApprovalStatus.Approved
    assert result.requested_approval is not None
    assert result.run.request_payload["graph_interrupt"]["value"]["approval_uid"] == next_approval.get_uid()
    assert run_repository.get_editor_run_by_approval(next_approval.id) is not None
    duplicate = run_repository.complete_editor_resume(
        claimed.id, claimed.attempt, "Continue", next_interrupt, next_approval
    )
    assert duplicate is not None and not duplicate.newly_applied
    with DbEngine.get_main_engine().connect() as connection:
        assert connection.scalar(select(func.count()).select_from(GraphApprovalRequest.__table__)) == 2
        assert connection.scalar(select(func.count()).select_from(EditorGraphApprovalRequest.__table__)) == 2


def test_board_chat_pause_persists_one_approval_and_is_idempotent(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    interrupt["value"]["run_id"] = "external-graph-run"
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert approval.run_id == run.client_task_id

    first = run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)
    assert first is not None
    saved_interrupt, newly_applied = first
    assert newly_applied
    assert saved_interrupt["value"]["approval_uid"] == approval.get_uid()
    assert saved_interrupt["value"]["status"] == "pending"

    duplicate = run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)
    assert duplicate == (saved_interrupt, False)
    assert run_repository.pause_board_chat(run.id, run.attempt - 1, "Partial answer", interrupt, approval) is None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Changed", interrupt, approval) is None
    assert not run_repository.finish(run.id, run.attempt, InternalBotRunStatus.Completed, output_text="late")

    saved_run = run_repository.get_board_chat_run(run.id)
    assert saved_run is not None
    assert saved_run.status == InternalBotRunStatus.AwaitingApproval
    assert saved_run.lease_expires_at is None
    with DbSession.use(readonly=False) as db:
        saved_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)
        ).first()
        details = db.exec(SqlBuilder.select.table(ChatGraphApprovalRequest)).all()
        approvals = db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all()
    assert saved_message is not None
    assert saved_message.message.content == "Partial answer"
    assert saved_message.message.graph_interrupt == saved_interrupt
    assert len(approvals) == len(details) == 1
    assert details[0].chat_history_id == ai_message.id
    assert details[0].approval_request_id == approvals[0].id


def test_board_chat_approval_selects_its_run_in_a_shared_session(
    run_repository: InternalBotRunRepository,
) -> None:
    previous, _ = run_repository.accept(make_run())
    run, _ = _claimed_board_chat(run_repository)
    with DbSession.use(readonly=False) as db:
        previous.chat_session_id = run.chat_session_id
        previous.user_id = run.user_id
        previous.project_id = run.project_id
        previous.graph_thread_id = run.graph_thread_id
        previous.status = InternalBotRunStatus.Completed
        db.update(previous)

    interrupt = _approval_interrupt(run.project_id.to_short_code())
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Approval needed", interrupt, approval)

    selected = run_repository.get_board_chat_run_by_approval(approval.id)
    assert selected is not None
    assert selected.id == run.id
    assert selected.status == InternalBotRunStatus.AwaitingApproval


def test_durable_board_chat_approval_cannot_bypass_resume_claim(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval) is not None
    with DbSession.use(readonly=False) as db:
        saved_approval = db.exec(
            SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval.id)
        ).first()
    assert saved_approval is not None
    assert run_repository.get_board_chat_run_by_approval(approval.id) is not None
    assert run_repository.get_board_chat_run_by_approval(SnowflakeID()) is None

    repository = Mock(internal_bot_run=run_repository)
    repository.graph_approval_request.get_by_id_like.return_value = saved_approval
    repository.graph_approval_request.get_expired_pending.return_value = [saved_approval]
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    graph_post = Mock(side_effect=AssertionError("The legacy REST path called Graph"))
    checkpoint_cleanup = Mock()
    monkeypatch.setattr(GraphApprovalRequestService, "_GraphApprovalRequestService__resume_graph", graph_post)
    monkeypatch.setattr(
        GraphApprovalRequestService, "_GraphApprovalRequestService__acknowledge_graph", checkpoint_cleanup
    )
    monkeypatch.setattr(service, "_GraphApprovalRequestService__get_project", lambda _approval: None)

    user = User(firstname="Test", lastname="Reviewer", email="reviewer@example.invalid", password=SecretStr("unused"))
    assert service.approve(saved_approval.get_uid(), user) is None
    assert service.reject(saved_approval.get_uid(), user) is None
    assert service.expire_pending() == [saved_approval]
    assert saved_approval.status == GraphApprovalStatus.Expired
    graph_post.assert_not_called()
    repository.graph_approval_request.update.assert_not_called()
    checkpoint_cleanup.assert_called_once()
    saved_run = run_repository.get_board_chat_run(run.id)
    assert saved_run is not None and saved_run.status == InternalBotRunStatus.Failed
    assert saved_run.lease_expires_at is None
    assert saved_run.finished_at is not None
    with DbSession.use(readonly=False) as db:
        saved_ai_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert saved_ai_message is not None
    assert saved_ai_message.message.graph_interrupt is not None
    assert saved_ai_message.message.graph_interrupt["value"]["status"] == "expired"
    assert (
        run_repository.claim_board_chat_resume(
            run.project_id,
            run.user_id,
            ai_message.id,
            "thread",
            "session",
            approval.id,
            {"approved": True, "rejected": False},
            30,
        )
        is None
    )


def test_durable_board_chat_cancellation_closes_run_without_graph_resume(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval) is not None
    with DbSession.use(readonly=False) as db:
        saved_approval = db.exec(
            SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval.id)
        ).first()
    assert saved_approval is not None

    repository = Mock(internal_bot_run=run_repository)
    repository.graph_approval_request.get_pending.return_value = [saved_approval]
    repository.graph_approval_request.get_detail.return_value = None
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    graph_resume = Mock(side_effect=AssertionError("The legacy REST path called Graph"))
    checkpoint_cleanup = Mock()
    approval_publisher = Mock()
    monkeypatch.setattr(GraphApprovalRequestService, "_GraphApprovalRequestService__resume_graph", graph_resume)
    monkeypatch.setattr(
        GraphApprovalRequestService, "_GraphApprovalRequestService__acknowledge_graph", checkpoint_cleanup
    )
    monkeypatch.setattr(service, "_GraphApprovalRequestService__matches_scope", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(GraphApprovalPublisher, "updated", approval_publisher)
    project = Project(id=run.project_id, owner_id=run.user_id, title="Test")

    assert service.cancel_pending_by_scope(
        project, "project", project.get_uid(), reason="Scope removed", origin_type=GraphApprovalOriginType.Chat
    ) == [saved_approval]
    assert saved_approval.status == GraphApprovalStatus.Cancelled
    graph_resume.assert_not_called()
    checkpoint_cleanup.assert_called_once()
    approval_publisher.assert_called_once()
    saved_run = run_repository.get_board_chat_run(run.id)
    assert saved_run is not None and saved_run.status == InternalBotRunStatus.Cancelled
    assert saved_run.error_message is not None and "Scope removed" in saved_run.error_message
    with DbSession.use(readonly=False) as db:
        saved_ai_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert saved_ai_message is not None and saved_ai_message.message.graph_interrupt is not None
    assert saved_ai_message.message.graph_interrupt["value"]["status"] == "cancelled"


def test_durable_board_chat_approval_close_rolls_back_on_run_failure(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    prepared = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = prepared.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval) is not None
    original_update = DbSession.update

    def fail_run_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, InternalBotRun):
            raise RuntimeError("Simulated approval close failure")
        original_update(db, model)

    monkeypatch.setattr(DbSession, "update", fail_run_update)
    with pytest.raises(RuntimeError, match="Simulated approval close failure"):
        run_repository.close_board_chat_approval(approval.id, GraphApprovalStatus.Expired, "Expired")

    with DbSession.use(readonly=False) as db:
        saved_run = db.exec(
            SqlBuilder.select.table(InternalBotRun).where(InternalBotRun.column("id") == run.id)
        ).first()
        saved_approval = db.exec(
            SqlBuilder.select.table(GraphApprovalRequest).where(GraphApprovalRequest.column("id") == approval.id)
        ).first()
        saved_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)
        ).first()
    assert saved_run is not None and saved_run.status == InternalBotRunStatus.AwaitingApproval
    assert saved_approval is not None and saved_approval.status == GraphApprovalStatus.Pending
    assert saved_message is not None and saved_message.message.graph_interrupt is not None
    assert saved_message.message.graph_interrupt["value"]["status"] == "pending"


def test_legacy_chat_approval_still_uses_existing_graph_path(monkeypatch: MonkeyPatch) -> None:
    approval = GraphApprovalRequest(thread_id="legacy-thread", request_type=GraphApprovalOriginType.Chat)
    repository = Mock()
    repository.graph_approval_request.get_by_id_like.return_value = approval
    repository.graph_approval_request.get_detail.return_value = None
    repository.internal_bot_run.get_board_chat_run_by_approval.return_value = None
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    graph_resume = Mock(return_value={"interrupts": [{"id": "next"}]})
    monkeypatch.setattr(GraphApprovalRequestService, "_GraphApprovalRequestService__resume_graph", graph_resume)
    monkeypatch.setattr(service, "_GraphApprovalRequestService__get_project", lambda _approval: None)

    user = User(firstname="Test", lastname="Reviewer", email="reviewer@example.invalid", password=SecretStr("unused"))
    assert service.approve(approval.get_uid(), user) is approval
    graph_resume.assert_called_once_with(approval, {"approved": True, "rejected": False})
    repository.graph_approval_request.update.assert_called_once_with(approval)
    assert approval.status == GraphApprovalStatus.Approved


def test_board_chat_pause_rejects_mismatched_approval_context(
    run_repository: InternalBotRunRepository,
) -> None:
    run, _ = _claimed_board_chat(run_repository)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    for field, value in (("scope_uid", "foreign-project"), ("thread_id", "foreign-thread"), ("session_id", "other")):
        invalid = {**interrupt, "value": {**interrupt["value"], field: value}}
        with pytest.raises(ValueError, match="does not belong"):
            approval_service.prepare_board_chat_interrupt(run, invalid)


def test_board_chat_pause_preserves_nonapproval_interrupt_on_retry(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = {"id": "human-input", "value": "Additional information needed"}
    first = run_repository.pause_board_chat(run.id, run.attempt, "", interrupt, None)
    assert first == (interrupt, True)
    assert run_repository.pause_board_chat(run.id, run.attempt, "", interrupt, None) == (interrupt, False)
    with DbSession.use(readonly=False) as db:
        saved = db.exec(SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)).first()
    assert saved is not None
    assert saved.message.graph_interrupt == interrupt


def test_board_chat_pause_rolls_back_approval_and_message_on_run_failure(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    original_update = DbSession.update

    def fail_run_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, InternalBotRun):
            raise RuntimeError("Simulated pause failure")
        original_update(db, model)

    monkeypatch.setattr(DbSession, "update", fail_run_update)
    with pytest.raises(RuntimeError, match="Simulated pause failure"):
        run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)

    saved_run = run_repository.get_board_chat_run(run.id)
    assert saved_run is not None and saved_run.status == InternalBotRunStatus.Streaming
    with DbSession.use(readonly=False) as db:
        saved_message = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)
        ).first()
        approvals = db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all()
        details = db.exec(SqlBuilder.select.table(ChatGraphApprovalRequest)).all()
    assert saved_message is not None and saved_message.message.content == ""
    assert saved_message.message.graph_interrupt is None
    assert approvals == details == []


def test_board_chat_resume_claims_once_with_matching_approval(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    assert run_repository.get_board_chat_run_by_ai_message(run.project_id, run.user_id, ai_message.id) is not None
    assert run_repository.get_board_chat_run_by_ai_message(SnowflakeID(99), run.user_id, ai_message.id) is None
    assert run_repository.get_board_chat_run_by_ai_message(run.project_id, SnowflakeID(99), ai_message.id) is None
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)

    resume = {"approved": True, "rejected": False}
    claimed = run_repository.claim_board_chat_resume(
        run.project_id, run.user_id, ai_message.id, "thread", "session", approval.id, resume, 30
    )
    assert claimed is not None
    assert claimed.status == InternalBotRunStatus.Resuming
    assert claimed.attempt == run.attempt + 1
    assert claimed.lease_expires_at is not None
    assert claimed.request_payload["resume"] == resume
    assert (
        run_repository.claim_board_chat_resume(
            run.project_id, run.user_id, ai_message.id, "thread", "session", approval.id, resume, 30
        )
        is None
    )


def test_board_chat_resume_rejects_other_owner_and_approval(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)

    resume = {"approved": False, "rejected": True}
    invalid_targets = (
        (SnowflakeID(99), run.user_id, ai_message.id, "thread", "session", approval.id),
        (run.project_id, SnowflakeID(99), ai_message.id, "thread", "session", approval.id),
        (run.project_id, run.user_id, SnowflakeID(99), "thread", "session", approval.id),
        (run.project_id, run.user_id, ai_message.id, "other", "session", approval.id),
        (run.project_id, run.user_id, ai_message.id, "thread", "other", approval.id),
        (run.project_id, run.user_id, ai_message.id, "thread", "session", SnowflakeID(99)),
        (run.project_id, run.user_id, ai_message.id, "thread", "session", None),
    )
    for target in invalid_targets:
        assert run_repository.claim_board_chat_resume(*target, resume, 30) is None

    saved = run_repository.get_board_chat_run(run.id)
    assert saved is not None
    assert saved.status == InternalBotRunStatus.AwaitingApproval
    assert saved.attempt == run.attempt
    assert "resume" not in saved.request_payload


def test_expired_board_chat_resume_becomes_uncertain_without_losing_interrupt(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)
    claimed = run_repository.claim_board_chat_resume(
        run.project_id,
        run.user_id,
        ai_message.id,
        "thread",
        "session",
        approval.id,
        {"approved": True, "rejected": False},
        1,
    )
    assert claimed is not None and claimed.lease_expires_at is not None

    expired = run_repository.mark_expired_uncertain(claimed.lease_expires_at + timedelta(seconds=1), 1)
    assert [item.id for item in expired] == [run.id]
    assert run_repository.mark_expired_uncertain(claimed.lease_expires_at + timedelta(seconds=1), 1) == []
    saved = run_repository.get_board_chat_run(run.id)
    assert saved is not None and saved.status == InternalBotRunStatus.Uncertain
    with DbSession.use(readonly=False) as db:
        history = db.exec(SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("id") == ai_message.id)).first()
    assert history is not None
    assert history.message.content == "Partial answer"
    assert history.message.graph_interrupt is not None


def test_board_chat_resume_result_resolves_approval_and_persists_response_once(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)
    claimed = run_repository.claim_board_chat_resume(
        run.project_id,
        run.user_id,
        ai_message.id,
        "thread",
        "session",
        approval.id,
        {"approved": True, "rejected": False},
        30,
    )
    assert claimed is not None
    assert run_repository.renew_lease(run.id, claimed.attempt, 30)
    assert not run_repository.renew_lease(run.id, claimed.attempt - 1, 30)

    first = run_repository.complete_board_chat_resume(run.id, claimed.attempt, "Completed answer", None, None)
    assert first is not None and first.newly_applied
    assert first.run.status == InternalBotRunStatus.Completed
    assert first.original_message.id == ai_message.id
    assert first.original_message.message.content == "Partial answer"
    assert first.original_message.message.graph_interrupt is not None
    assert first.original_message.message.graph_interrupt["value"]["status"] == "approved"
    assert first.resumed_message is not None
    assert first.resumed_message.message.content == "Completed answer"
    assert first.resolved_approval is not None and first.resolved_approval.status == GraphApprovalStatus.Approved
    assert first.requested_approval is None
    assert first.run.lease_expires_at is None

    duplicate = run_repository.complete_board_chat_resume(run.id, claimed.attempt, "Completed answer", None, None)
    assert duplicate is not None and not duplicate.newly_applied
    assert duplicate.resumed_message is not None
    assert duplicate.resumed_message.id == first.resumed_message.id
    assert run_repository.complete_board_chat_resume(run.id, claimed.attempt, "different", None, None) is None
    with DbSession.use(readonly=False) as db:
        responses = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("is_received").is_(True))
        ).all()
    assert len(responses) == 2


def test_board_chat_resume_rejection_keeps_partial_response_and_reason(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "Partial answer", interrupt, approval)
    claimed = run_repository.claim_board_chat_resume(
        run.project_id,
        run.user_id,
        ai_message.id,
        "thread",
        "session",
        approval.id,
        {"approved": False, "rejected": True, "reason": "Not authorized"},
        30,
    )
    assert claimed is not None

    result = run_repository.complete_board_chat_resume(run.id, claimed.attempt, "Graph approval rejected.", None, None)
    assert result is not None and result.newly_applied
    assert result.resumed_message is None
    assert result.original_message.message.content == "Partial answer"
    assert result.original_message.message.graph_interrupt is not None
    value = result.original_message.message.graph_interrupt["value"]
    assert value["status"] == "rejected"
    assert value["rejection_reason"] == "Not authorized"
    assert result.resolved_approval is not None
    assert result.resolved_approval.status == GraphApprovalStatus.Rejected
    assert result.resolved_approval.rejection_reason == "Not authorized"


def test_board_chat_resume_can_pause_again_with_new_approval(
    run_repository: InternalBotRunRepository,
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "First answer", interrupt, approval)
    claimed = run_repository.claim_board_chat_resume(
        run.project_id,
        run.user_id,
        ai_message.id,
        "thread",
        "session",
        approval.id,
        {"approved": True, "rejected": False},
        30,
    )
    assert claimed is not None
    assert run_repository.close_board_chat_approval(approval.id, GraphApprovalStatus.Expired, "Expired") is None
    next_interrupt = {**interrupt, "id": "graph-interrupt-2"}
    next_approval = approval_service.prepare_board_chat_interrupt(claimed, next_interrupt)
    assert next_approval is not None

    result = run_repository.complete_board_chat_resume(
        run.id, claimed.attempt, "Second answer", next_interrupt, next_approval
    )
    assert result is not None and result.newly_applied
    assert result.run.status == InternalBotRunStatus.AwaitingApproval
    assert result.original_message.message.graph_interrupt is not None
    assert result.original_message.message.graph_interrupt["value"]["status"] == "approved"
    assert result.resumed_message is not None
    assert result.resumed_message.message.graph_interrupt is not None
    assert result.resumed_message.message.graph_interrupt["value"]["status"] == "pending"
    assert result.run.ai_chat_history_id == result.resumed_message.id
    assert result.requested_approval is not None
    assert result.requested_approval.id == next_approval.id
    assert run_repository.get_board_chat_run_by_approval(approval.id) is not None
    assert run_repository.get_board_chat_run_by_approval(next_approval.id) is not None

    duplicate = run_repository.complete_board_chat_resume(
        run.id, claimed.attempt, "Second answer", next_interrupt, next_approval
    )
    assert duplicate is not None and not duplicate.newly_applied
    assert duplicate.resumed_message is not None and duplicate.resumed_message.id == result.resumed_message.id
    with DbSession.use(readonly=False) as db:
        approvals = db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all()
        details = db.exec(SqlBuilder.select.table(ChatGraphApprovalRequest)).all()
    assert len(approvals) == len(details) == 2
    assert (
        run_repository.claim_board_chat_resume(
            run.project_id,
            run.user_id,
            result.resumed_message.id,
            "thread",
            "session",
            next_approval.id,
            {"approved": False, "rejected": True},
            30,
        )
        is not None
    )
    assert (
        run_repository.complete_board_chat_resume(
            run.id, claimed.attempt, "Second answer", next_interrupt, next_approval
        )
        is None
    )


def test_board_chat_resume_result_rolls_back_every_record_on_run_failure(
    run_repository: InternalBotRunRepository, monkeypatch: MonkeyPatch
) -> None:
    run, ai_message = _claimed_board_chat(run_repository)
    approval_service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, Mock())
    interrupt = _approval_interrupt(run.project_id.to_short_code())
    approval = approval_service.prepare_board_chat_interrupt(run, interrupt)
    assert approval is not None
    assert run_repository.pause_board_chat(run.id, run.attempt, "First answer", interrupt, approval)
    claimed = run_repository.claim_board_chat_resume(
        run.project_id,
        run.user_id,
        ai_message.id,
        "thread",
        "session",
        approval.id,
        {"approved": True, "rejected": False},
        30,
    )
    assert claimed is not None
    next_interrupt = {**interrupt, "id": "graph-interrupt-2"}
    next_approval = approval_service.prepare_board_chat_interrupt(claimed, next_interrupt)
    assert next_approval is not None
    original_update = DbSession.update

    def fail_run_update(db: DbSession, model: BaseDbModel) -> None:
        if isinstance(model, InternalBotRun):
            raise RuntimeError("Simulated resume result failure")
        original_update(db, model)

    with monkeypatch.context() as patcher:
        patcher.setattr(DbSession, "update", fail_run_update)
        with pytest.raises(RuntimeError, match="Simulated resume result failure"):
            run_repository.complete_board_chat_resume(
                run.id, claimed.attempt, "Second answer", next_interrupt, next_approval
            )

    saved = run_repository.get_board_chat_run(run.id)
    assert saved is not None and saved.status == InternalBotRunStatus.Resuming
    with DbSession.use(readonly=False) as db:
        approvals = db.exec(SqlBuilder.select.table(GraphApprovalRequest)).all()
        details = db.exec(SqlBuilder.select.table(ChatGraphApprovalRequest)).all()
        messages = db.exec(
            SqlBuilder.select.table(ChatHistory).where(ChatHistory.column("is_received").is_(True))
        ).all()
    assert len(approvals) == len(details) == len(messages) == 1
    assert approvals[0].status == GraphApprovalStatus.Pending
    assert messages[0].id == ai_message.id
    assert messages[0].message.graph_interrupt is not None
    assert messages[0].message.graph_interrupt["value"]["status"] == "pending"
