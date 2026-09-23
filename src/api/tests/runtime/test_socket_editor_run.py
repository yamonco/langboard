from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import orjson
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.auth import SocketAuthApi
from langboard.routes.auth.forms import (
    SocketBoardChatFinishForm,
    SocketBoardChatLeaseForm,
    SocketBoardChatPauseForm,
    SocketBoardChatResumeResultForm,
    SocketEditorCancelForm,
    SocketEditorResumeClaimForm,
    SocketEditorRunForm,
)
from langboard_shared.core.routing import ApiException, AppRouter, SocketTopic
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.User import User
from langboard_shared.domain.services import DomainService
from pydantic import ValidationError
from pytest import MonkeyPatch


PROJECT_ID = SnowflakeID(2)
SCOPE_ID = SnowflakeID(4)
PROJECT_UID = PROJECT_ID.to_short_code()
SCOPE_UID = SCOPE_ID.to_short_code()


def make_request(secret: str = "s" * 32, bearer: str | None = "user-token") -> Request:
    headers = [(b"x-socket-internal-secret", secret.encode())]
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "headers": headers})


def make_form(kind: str = "editor_chat") -> SocketEditorRunForm:
    data: dict[str, object] = {
        "project_uid": PROJECT_UID,
        "scope_uid": SCOPE_UID,
        "document_name": f"card:{SCOPE_UID}:description",
        "task_id": uuid4(),
        "kind": kind,
        "system": "Editor instructions",
    }
    if kind == "editor_chat":
        data["messages"] = [{"role": "user", "content": "Hello"}]
    else:
        data["prompt"] = "Continue the paragraph"
    return SocketEditorRunForm.model_validate(data)


def allow_user(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32, AI_REQUEST_TIMEOUT=120)
    )
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "decode_access_token", lambda token: {"sub": "1"})
    monkeypatch.setattr(
        SocketAuthApi.Auth,
        "get_user_by_id",
        lambda user_id: User.model_construct(id=SnowflakeID(1), deleted_at=None, activated_at=SafeDateTime.now()),
    )
    monkeypatch.setattr(
        SocketAuthApi,
        "authorized_editor_document_subscription",
        lambda service, user, document_name: (SocketTopic.BoardCard, SCOPE_UID),
    )


def make_service() -> Mock:
    service = Mock(spec=DomainService)
    project = SimpleNamespace(id=PROJECT_ID)
    bot = SimpleNamespace(
        id=SnowflakeID(3), platform=BotPlatform.Default, platform_running_type=BotPlatformRunningType.Default
    )
    service.project.get_by_id_like.return_value = project
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    service.project.get_assigned_internal_bot_by_type.return_value = (bot, Mock())
    service.internal_bot_run.accept_editor.return_value = (
        SimpleNamespace(get_uid=lambda: "run-uid", status=InternalBotRunStatus.Accepted),
        True,
    )
    return service


def make_accepted_run(service: Mock) -> SimpleNamespace:
    run = SimpleNamespace(
        id=SnowflakeID(50),
        client_task_id=str(uuid4()),
        kind=InternalBotRunKind.EditorChat,
        status=InternalBotRunStatus.Accepted,
        user_id=SnowflakeID(1),
        project_id=PROJECT_ID,
        internal_bot_id=SnowflakeID(3),
        scope_table="card",
        scope_uid=SCOPE_UID,
        request_payload={"document_name": f"card:{SCOPE_UID}:description"},
        attempt=1,
        output_text="",
        error_message=None,
        get_uid=lambda: SnowflakeID(50).to_short_code(),
    )
    service.internal_bot_run.get_editor_run.return_value = run
    service.internal_bot_run.start_editor.return_value = (run, {"session_id": "session", "thread_id": "thread"})
    service.internal_bot_run.finish_editor.return_value = True
    return run


@pytest.mark.parametrize("kind", ["editor_chat", "editor_copilot"])
def test_editor_run_accepts_authorized_document_and_kind(monkeypatch: MonkeyPatch, kind: str) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form(kind)

    response = SocketAuthApi.accept_socket_editor_run(make_request(), form, service)

    assert orjson.loads(response.body) == {"run_uid": "run-uid", "status": "accepted", "accepted": True}
    assert service.internal_bot_run.accept_editor.call_args.kwargs["kind"] == InternalBotRunKind(kind)
    assert service.internal_bot_run.accept_editor.call_args.kwargs["scope_table"] == "card"
    assert service.internal_bot_run.accept_editor.call_args.kwargs["document_name"] == form.document_name


def test_editor_run_rejects_foreign_scope_and_conflict(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form()
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))

    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.accept_socket_editor_run(make_request(), form, service)
    service.internal_bot_run.accept_editor.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    service.internal_bot_run.accept_editor.side_effect = ValueError("A different request uses this identity")
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.accept_socket_editor_run(make_request(), form, service)


def test_editor_run_requires_both_credentials_and_default_bot(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form()

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.accept_socket_editor_run(make_request(secret="wrong"), form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.accept_socket_editor_run(make_request(bearer=None), form, service)
    service.internal_bot_run.accept_editor.assert_not_called()

    service.project.get_assigned_internal_bot_by_type.return_value[0].platform = BotPlatform.Langflow
    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.accept_socket_editor_run(make_request(), form, service)


def test_editor_run_form_rejects_mixed_or_extra_payload() -> None:
    valid = make_form().model_dump()
    with pytest.raises(ValidationError):
        SocketEditorRunForm.model_validate({**valid, "prompt": "injected"})
    with pytest.raises(ValidationError):
        SocketEditorRunForm.model_validate({**valid, "file_path": "/tmp/secret"})
    with pytest.raises(ValidationError):
        SocketEditorRunForm.model_validate({**valid, "messages": [{"role": "tool", "content": "bad"}]})


def test_editor_run_http_route_enforces_credentials_and_schema(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    for endpoint in (
        SocketAuthApi.accept_socket_editor_run,
        SocketAuthApi.cancel_socket_editor_run,
        SocketAuthApi.get_socket_editor_run_status,
        SocketAuthApi.start_socket_editor_run,
        SocketAuthApi.renew_socket_editor_run_lease,
        SocketAuthApi.finish_socket_editor_run,
    ):
        route = next(
            route for route in AppRouter.api.routes if isinstance(route, APIRoute) and route.endpoint is endpoint
        )
        dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
        assert dependency is not None
        app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    body = make_form().model_dump(mode="json")
    path = "/auth/socket/editor-ai/runs"

    assert client.post(path, json=body, headers={"Authorization": "Bearer user-token"}).status_code == 401
    assert client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 401
    response = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {"run_uid": "run-uid", "status": "accepted", "accepted": True}
    invalid = client.post(
        path,
        json={**body, "file_path": "/tmp/secret"},
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert invalid.status_code == 400
    service.internal_bot_run.accept_editor.assert_called_once()

    service.internal_bot_run.cancel_editor.return_value = SimpleNamespace(
        get_uid=lambda: "run-uid", status=InternalBotRunStatus.Cancelled, client_task_id=body["task_id"]
    )
    cancel = client.post(
        "/auth/socket/editor-ai/cancel",
        json={"project_uid": PROJECT_UID, "task_id": body["task_id"], "kind": "editor_chat"},
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert cancel.status_code == 200
    assert cancel.json() == {"run_uid": "run-uid", "status": "cancelled", "task_id": body["task_id"]}

    run = make_accepted_run(service)
    start = client.post(
        f"{path}/{run.get_uid()}/start",
        headers={"X-Socket-Internal-Secret": "s" * 32},
    )
    assert start.status_code == 200
    assert start.json()["graph_request"] == {"session_id": "session", "thread_id": "thread"}

    run.status = InternalBotRunStatus.Streaming
    service.internal_bot_run.renew_editor_lease.return_value = True
    lease = client.post(
        f"{path}/{run.get_uid()}/lease",
        json={"attempt": 1},
        headers={"X-Socket-Internal-Secret": "s" * 32},
    )
    assert lease.status_code == 200
    assert lease.json()["status"] == "streaming"

    finish = client.post(
        f"{path}/{run.get_uid()}/finish",
        json={"attempt": 1, "status": "completed", "output_text": "Done"},
        headers={"X-Socket-Internal-Secret": "s" * 32},
    )
    assert finish.status_code == 200
    assert finish.json()["status"] == "completed"

    run.status = InternalBotRunStatus.Completed
    run.client_task_id = body["task_id"]
    run.output_text = "Done"
    service.internal_bot_run.get_editor_run_by_task.return_value = run
    status_response = client.post(
        "/auth/socket/editor-ai/status",
        json={"project_uid": PROJECT_UID, "task_id": body["task_id"], "kind": "editor_chat"},
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert status_response.status_code == 200
    assert status_response.json() == {
        "run_uid": run.get_uid(),
        "task_id": run.client_task_id,
        "kind": "editor_chat",
        "status": "completed",
        "attempt": run.attempt,
        "output_text": "Done",
        "error_message": None,
    }


def test_editor_run_start_rechecks_scope_and_bot_before_claim(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)

    response = SocketAuthApi.start_socket_editor_run(make_request(bearer=None), run.get_uid(), service)
    assert orjson.loads(response.body) == {
        "run_uid": run.get_uid(),
        "attempt": 1,
        "graph_request": {"session_id": "session", "thread_id": "thread"},
    }
    service.internal_bot_run.start_editor.assert_called_once()

    service.internal_bot_run.start_editor.reset_mock()
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.start_socket_editor_run(make_request(bearer=None), run.get_uid(), service)
    service.internal_bot_run.start_editor.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    service.project.get_assigned_internal_bot_by_type.return_value[0].id = SnowflakeID(99)
    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.start_socket_editor_run(make_request(bearer=None), run.get_uid(), service)
    service.internal_bot_run.start_editor.assert_not_called()


def test_editor_run_start_and_finish_reject_wrong_secret_or_fence(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    finish_form = SocketBoardChatFinishForm(attempt=1, status="completed", output_text="Done")

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.start_socket_editor_run(make_request(secret="wrong"), run.get_uid(), service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.finish_socket_editor_run(make_request(secret="wrong"), run.get_uid(), finish_form, service)
    service.internal_bot_run.start_editor.assert_not_called()
    service.internal_bot_run.finish_editor.assert_not_called()

    run.status = InternalBotRunStatus.Streaming
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.start_socket_editor_run(make_request(bearer=None), run.get_uid(), service)

    service.internal_bot_run.finish_editor.return_value = False
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.finish_socket_editor_run(make_request(bearer=None), run.get_uid(), finish_form, service)
    service.internal_bot_run.finish_editor.assert_called_once_with(
        run.id, 1, InternalBotRunStatus.Completed, "Done", None
    )


def test_editor_resume_failure_expires_approval_and_publishes_once(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    run.status = InternalBotRunStatus.Resuming
    run.attempt = 2
    failed_run = SimpleNamespace(status=InternalBotRunStatus.Failed)
    approval = SimpleNamespace()
    service.internal_bot_run.fail_editor_resume.return_value = (failed_run, approval, True)
    service.graph_approval_request.get_api_response.return_value = {"uid": "approval-uid", "status": "expired"}
    published = Mock()
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "updated", published)
    form = SocketBoardChatFinishForm(
        attempt=2,
        status="failed",
        error_message="Editor AI scope access was revoked",
    )

    response = SocketAuthApi.finish_socket_editor_run(make_request(bearer=None), run.get_uid(), form, service)

    assert orjson.loads(response.body) == {"run_uid": run.get_uid(), "attempt": 2, "status": "failed"}
    service.internal_bot_run.fail_editor_resume.assert_called_once_with(run.id, 2, "Editor AI scope access was revoked")
    service.internal_bot_run.finish_editor.assert_not_called()
    published.assert_called_once_with(
        service.project.get_by_id_like.return_value,
        {"uid": "approval-uid", "status": "expired"},
    )

    completed = SocketBoardChatFinishForm(attempt=2, status="completed", output_text="late")
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.finish_socket_editor_run(make_request(bearer=None), run.get_uid(), completed, service)


def test_editor_pause_requires_internal_secret_and_current_document_access(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    run.status = InternalBotRunStatus.Streaming
    interrupt = {"value": {"type": "approval_request"}}
    form = SocketBoardChatPauseForm(attempt=1, output_text="Partial answer", interrupt=interrupt)
    approval = SimpleNamespace(get_uid=lambda: "approval-uid")
    service.internal_bot_run.pause_editor.return_value = (interrupt, approval)
    service.graph_approval_request.get_api_response.return_value = {"uid": "approval-uid"}
    published = Mock()
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "requested", published)

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.pause_socket_editor_run(make_request(secret="wrong"), run.get_uid(), form, service)
    service.internal_bot_run.pause_editor.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.pause_socket_editor_run(make_request(bearer=None), run.get_uid(), form, service)
    service.internal_bot_run.pause_editor.assert_not_called()
    published.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    response = SocketAuthApi.pause_socket_editor_run(make_request(bearer=None), run.get_uid(), form, service)
    assert orjson.loads(response.body) == {
        "run_uid": run.get_uid(),
        "attempt": 1,
        "status": "awaiting_approval",
        "interrupt": interrupt,
    }
    service.internal_bot_run.pause_editor.assert_called_once_with(run.id, 1, "Partial answer", interrupt)
    published.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "approval-uid"})

    service.internal_bot_run.pause_editor.return_value = (interrupt, None)
    SocketAuthApi.pause_socket_editor_run(make_request(bearer=None), run.get_uid(), form, service)
    published.assert_called_once()

    service.internal_bot_run.pause_editor.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.pause_socket_editor_run(make_request(bearer=None), run.get_uid(), form, service)
    published.assert_called_once()


def test_editor_resume_claim_checks_approver_scope_and_keeps_token_out_of_run(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    run.status = InternalBotRunStatus.AwaitingApproval
    run.graph_thread_id = "editor-thread"
    run.graph_session_id = "editor-session"
    service.internal_bot_run.get_editor_run_by_approval.return_value = run
    service.project.get_user_role_actions_by_project.return_value = ["update"]
    service.internal_bot_run.claim_editor_resume.return_value = run
    token_factory = Mock(return_value="one-time-token")
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "create_bot_one_time_token", token_factory)
    form = SocketEditorResumeClaimForm.model_validate(
        {"project_uid": PROJECT_UID, "resume": {"approved": True, "rejected": False}}
    )
    approval_uid = SnowflakeID(77).to_short_code()

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.claim_socket_editor_resume(make_request(secret="wrong"), approval_uid, form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.claim_socket_editor_resume(make_request(bearer=None), approval_uid, form, service)
    service.internal_bot_run.claim_editor_resume.assert_not_called()

    service.project.get_user_role_actions_by_project.return_value = ["read"]
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.claim_socket_editor_resume(make_request(), approval_uid, form, service)
    token_factory.assert_not_called()

    service.project.get_user_role_actions_by_project.return_value = ["update"]
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.claim_socket_editor_resume(make_request(), approval_uid, form, service)
    token_factory.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    response = SocketAuthApi.claim_socket_editor_resume(make_request(), approval_uid, form, service)
    payload = orjson.loads(response.body)
    assert payload["run_uid"] == run.get_uid()
    assert payload["session_id"] == "editor-session"
    assert payload["thread_id"] == "editor-thread"
    assert payload["resume"]["app_api_token"] == "one-time-token"
    service.internal_bot_run.claim_editor_resume.assert_called_once_with(
        SnowflakeID(77), PROJECT_ID, SnowflakeID(1), {"approved": True, "rejected": False}, 150
    )
    assert "app_api_token" not in service.internal_bot_run.claim_editor_resume.call_args.args[3]


def test_editor_resume_result_publishes_only_newly_persisted_approvals(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    run.status = InternalBotRunStatus.Resuming
    run.graph_thread_id = "editor-thread"
    run.graph_session_id = "editor-session"
    run.output_text = "Finished"
    resolved = SimpleNamespace(get_uid=lambda: "resolved")
    requested = SimpleNamespace(get_uid=lambda: "requested")
    service.internal_bot_run.complete_editor_resume.return_value = (run, resolved, requested, True)
    service.graph_approval_request.get_api_response.side_effect = [
        {"uid": "resolved"},
        {"uid": "requested"},
    ]
    updated = Mock()
    requested_publish = Mock()
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "updated", updated)
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "requested", requested_publish)
    form = SocketBoardChatResumeResultForm(
        attempt=2,
        thread_id="editor-thread",
        session_id="editor-session",
        response_text="Finished",
        interrupt={"value": {"type": "approval_request"}},
    )

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.complete_socket_editor_resume(make_request(secret="wrong"), run.get_uid(), form, service)
    updated.assert_not_called()
    requested_publish.assert_not_called()

    service.internal_bot_run.complete_editor_resume.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.complete_socket_editor_resume(make_request(bearer=None), run.get_uid(), form, service)
    updated.assert_not_called()
    requested_publish.assert_not_called()

    service.internal_bot_run.complete_editor_resume.return_value = (run, resolved, requested, True)
    response = SocketAuthApi.complete_socket_editor_resume(make_request(bearer=None), run.get_uid(), form, service)
    assert orjson.loads(response.body)["status"] == "resuming"
    updated.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "resolved"})
    requested_publish.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "requested"})

    service.internal_bot_run.complete_editor_resume.return_value = (run, None, None, False)
    SocketAuthApi.complete_socket_editor_resume(make_request(bearer=None), run.get_uid(), form, service)
    updated.assert_called_once()
    requested_publish.assert_called_once()


def test_editor_run_lease_requires_streaming_attempt(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    lease_form = SocketBoardChatLeaseForm(attempt=1)

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.renew_socket_editor_run_lease(make_request(secret="wrong"), run.get_uid(), lease_form, service)
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.renew_socket_editor_run_lease(make_request(bearer=None), run.get_uid(), lease_form, service)
    service.internal_bot_run.renew_editor_lease.assert_not_called()

    run.status = InternalBotRunStatus.Streaming
    service.internal_bot_run.renew_editor_lease.return_value = True
    response = SocketAuthApi.renew_socket_editor_run_lease(
        make_request(bearer=None), run.get_uid(), lease_form, service
    )
    assert orjson.loads(response.body) == {"run_uid": run.get_uid(), "attempt": 1, "status": "streaming"}
    service.internal_bot_run.renew_editor_lease.assert_called_once_with(run.id, 1, 150)

    service.internal_bot_run.renew_editor_lease.return_value = False
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.renew_socket_editor_run_lease(make_request(bearer=None), run.get_uid(), lease_form, service)


def test_editor_resume_lease_requires_resuming_attempt_and_current_scope(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    lease_form = SocketBoardChatLeaseForm(attempt=2)

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.renew_socket_editor_resume_lease(make_request(secret="wrong"), run.get_uid(), lease_form, service)
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.renew_socket_editor_resume_lease(make_request(bearer=None), run.get_uid(), lease_form, service)
    service.internal_bot_run.renew_editor_lease.assert_not_called()

    run.status = InternalBotRunStatus.Resuming
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_editor_resume_lease(make_request(bearer=None), run.get_uid(), lease_form, service)
    service.internal_bot_run.renew_editor_lease.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    service.internal_bot_run.renew_editor_lease.return_value = True
    response = SocketAuthApi.renew_socket_editor_resume_lease(
        make_request(bearer=None), run.get_uid(), lease_form, service
    )
    assert orjson.loads(response.body) == {"run_uid": run.get_uid(), "attempt": 2, "status": "resuming"}
    service.internal_bot_run.renew_editor_lease.assert_called_once_with(run.id, 2, 150)


def test_editor_run_lease_rechecks_scope_before_renewal(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = make_accepted_run(service)
    run.status = InternalBotRunStatus.Streaming
    lease_form = SocketBoardChatLeaseForm(attempt=1)

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_editor_run_lease(make_request(bearer=None), run.get_uid(), lease_form, service)
    service.internal_bot_run.renew_editor_lease.assert_not_called()

    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=PROJECT_ID)
    monkeypatch.setattr(SocketAuthApi, "authorized_editor_document_subscription", lambda *_args: None)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_editor_run_lease(make_request(bearer=None), run.get_uid(), lease_form, service)
    service.internal_bot_run.renew_editor_lease.assert_not_called()


def test_editor_run_cancel_requires_both_credentials_and_owned_identity(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = SocketEditorCancelForm(project_uid=PROJECT_UID, task_id=uuid4(), kind="editor_chat")
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.cancel_socket_editor_run(make_request(secret="wrong"), form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.cancel_socket_editor_run(make_request(bearer=None), form, service)
    service.internal_bot_run.cancel_editor.assert_not_called()

    service.internal_bot_run.cancel_editor.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.cancel_socket_editor_run(make_request(), form, service)
    service.internal_bot_run.cancel_editor.assert_called_once_with(
        InternalBotRunKind.EditorChat, form.task_id, SnowflakeID(1), PROJECT_ID
    )


def test_editor_recovery_list_requires_internal_secret_and_bounds_cursor(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    service.internal_bot_run.list_accepted_editor_runs.return_value = [
        SimpleNamespace(
            get_uid=lambda: "run-uid",
            project_id=PROJECT_ID,
            client_task_id=str(uuid4()),
            kind=InternalBotRunKind.EditorCopilot,
        )
    ]
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.list_accepted_socket_editor_runs
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = "/auth/socket/editor-ai/runs/accepted?limit=1"

    assert client.get(path).status_code == 401
    response = client.get(path, headers={"X-Socket-Internal-Secret": "s" * 32})
    assert response.status_code == 200
    assert response.json()["runs"][0] == {
        "run_uid": "run-uid",
        "project_uid": PROJECT_UID,
        "task_id": service.internal_bot_run.list_accepted_editor_runs.return_value[0].client_task_id,
        "kind": "editor_copilot",
    }
    service.internal_bot_run.list_accepted_editor_runs.assert_called_once_with(1, None)

    bad_limit = client.get(f"{path}01", headers={"X-Socket-Internal-Secret": "s" * 32})
    assert bad_limit.status_code == 400
    bad_cursor = client.get(
        f"{path}&after_run_uid=invalid",
        headers={"X-Socket-Internal-Secret": "s" * 32},
    )
    assert bad_cursor.status_code == 403
    service.internal_bot_run.list_accepted_editor_runs.assert_called_once()
