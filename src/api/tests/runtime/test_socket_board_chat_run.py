from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock
from uuid import UUID, uuid4
import orjson
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.auth import SocketAuthApi
from langboard.routes.auth.forms import (
    SocketBoardChatCancelForm,
    SocketBoardChatFinishForm,
    SocketBoardChatLeaseForm,
    SocketBoardChatPauseForm,
    SocketBoardChatResumeClaimForm,
    SocketBoardChatResumeResultForm,
    SocketBoardChatRunForm,
    SocketBoardChatStartForm,
)
from langboard.routes.auth.forms.Socket import SocketBoardChatResumeDecision
from langboard_shared.core.routing import ApiException, AppRouter, EEditorCollaborationType
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBotRun import InternalBotRun, InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.User import User
from langboard_shared.domain.services import DomainService
from pydantic import ValidationError
from pytest import MonkeyPatch


PROJECT_UID = SnowflakeID(2).to_short_code()
CARD_UID = SnowflakeID(4).to_short_code()


def make_request(secret: str = "s" * 32, bearer: str | None = "user-token") -> Request:
    headers = [(b"x-socket-internal-secret", secret.encode())]
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "headers": headers})


def make_service() -> Mock:
    service = Mock(spec=DomainService)
    project = SimpleNamespace(id=SnowflakeID(2))
    bot = SimpleNamespace(
        id=SnowflakeID(3),
        platform=BotPlatform.Default,
        platform_running_type=BotPlatformRunningType.Default,
    )
    service.project.get_by_id_like.return_value = project
    service.project.get_assigned_internal_bot_by_type.return_value = (bot, Mock())
    service.internal_bot_run.accept_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: "run-uid", status=InternalBotRunStatus.Accepted),
        True,
        SimpleNamespace(api_response=lambda: {"title": "Untitled"}),
        SimpleNamespace(api_response=lambda: {"uid": "session-uid"}, get_uid=lambda: "session-uid"),
        SimpleNamespace(api_response=lambda: {"uid": "message-uid", "message": {"content": "hello"}}),
    )
    return service


def make_form(
    *,
    scope_table: Literal["project", "project_column", "card", "project_wiki"] = "project",
    scope_uid: str | None = None,
    session_uid: str | None = None,
    task_id: UUID | None = None,
    file_token: str | None = None,
    permission_level: Literal["read", "edit", "full_access"] = "read",
) -> SocketBoardChatRunForm:
    return SocketBoardChatRunForm(
        task_id=task_id or uuid4(),
        message="" if file_token else "hello",
        file_token=file_token,
        scope_table=scope_table,
        scope_uid=scope_uid,
        session_uid=session_uid,
        api_permission_level=permission_level,
    )


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
    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: True)


@pytest.mark.parametrize(
    ("scope_table", "service_name"),
    [("card", "card"), ("project_column", "project_column"), ("project_wiki", "project_wiki")],
)
def test_board_chat_run_accepts_only_authorized_scope(
    monkeypatch: MonkeyPatch,
    scope_table: Literal["card", "project_column", "project_wiki"],
    service_name: Literal["card", "project_column", "project_wiki"],
) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form(scope_table=scope_table, scope_uid=CARD_UID)
    scope_service = getattr(service, service_name)
    scope_service.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(2))

    response = SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, form, service)
    assert orjson.loads(response.body) == {
        "run_uid": "run-uid",
        "status": "accepted",
        "accepted": True,
        "session": {"title": "Untitled", "uid": "session-uid"},
        "user_message": {"uid": "message-uid", "message": {"content": "hello"}, "chat_session_uid": "session-uid"},
    }
    service.internal_bot_run.accept_board_chat.assert_called_once()

    scope_service.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.accept_board_chat.assert_called_once()


def test_board_chat_run_maps_identity_conflict_to_http_409(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    service.internal_bot_run.accept_board_chat.side_effect = ValueError(
        "A different AI request already uses this task identity"
    )

    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, make_form(), service)


def test_board_chat_run_binds_a_server_owned_attachment_ticket(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    task_id = uuid4()
    token = "t" * 32
    ticket = {
        "user_id": 1,
        "project_id": 2,
        "bot_id": 3,
        "task_id": str(task_id),
        "file_id": "file-id",
        "path": "user/file.txt",
    }
    service.project.get_assigned_internal_bot_by_type.return_value[0].platform = BotPlatform.Langflow
    service.project.get_assigned_internal_bot_by_type.return_value[
        0
    ].platform_running_type = BotPlatformRunningType.Endpoint
    monkeypatch.setattr(
        SocketAuthApi, "get_board_chat_attachment_ticket", lambda value: ticket if value == token else None
    )
    set_ticket = Mock()
    monkeypatch.setattr(SocketAuthApi, "set_board_chat_attachment_ticket", set_ticket)

    response = SocketAuthApi.accept_socket_board_chat_run(
        make_request(), PROJECT_UID, make_form(task_id=task_id, file_token=token), service
    )

    assert orjson.loads(response.body)["status"] == "accepted"
    assert service.internal_bot_run.accept_board_chat.call_args.kwargs["attachment"] == {
        "file_id": "file-id",
        "path": "user/file.txt",
        "token": token,
    }
    set_ticket.assert_called_once_with(token, {**ticket, "run_uid": "run-uid"})


def test_board_chat_run_rejects_an_attachment_ticket_from_another_project(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    token = "t" * 32
    monkeypatch.setattr(
        SocketAuthApi,
        "get_board_chat_attachment_ticket",
        lambda value: {
            "user_id": 1,
            "project_id": 99,
            "bot_id": 3,
            "task_id": str(uuid4()),
            "file_id": "id",
            "path": "path",
        },
    )

    with pytest.raises(ApiException.NotFound_404):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, make_form(file_token=token), service)

    service.internal_bot_run.accept_board_chat.assert_not_called()


def test_board_chat_run_requires_server_secret_and_user_bearer(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form()

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.accept_socket_board_chat_run(make_request(secret="wrong"), PROJECT_UID, form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.accept_socket_board_chat_run(make_request(secret="é"), PROJECT_UID, form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.accept_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, form, service)
    service.internal_bot_run.accept_board_chat.assert_not_called()

    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET=""))
    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, form, service)


def test_board_chat_run_rechecks_membership_and_session_owner(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    form = make_form(session_uid=SnowflakeID(5).to_short_code())

    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: False)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.accept_board_chat.assert_not_called()

    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: True)
    service.internal_bot_run.accept_board_chat.side_effect = PermissionError("Chat session is not assigned")
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.accept_board_chat.assert_called_once()


@pytest.mark.parametrize("permission_level", ["edit", "full_access"])
def test_board_chat_run_rejects_removed_project_update_permission_before_accept(
    monkeypatch: MonkeyPatch,
    permission_level: Literal["edit", "full_access"],
) -> None:
    allow_user(monkeypatch)
    service = make_service()
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Read.value]

    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.accept_socket_board_chat_run(
            make_request(),
            PROJECT_UID,
            make_form(permission_level=permission_level),
            service,
        )

    service.internal_bot_run.accept_board_chat.assert_not_called()


def test_board_chat_run_rejects_invalid_scope_before_accept(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    with pytest.raises(ApiException.BadRequest_400):
        SocketAuthApi.accept_socket_board_chat_run(
            make_request(), PROJECT_UID, make_form(scope_table="project", scope_uid=CARD_UID), service
        )
    with pytest.raises(ApiException.BadRequest_400):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, make_form(scope_table="card"), service)
    service.internal_bot_run.accept_board_chat.assert_not_called()


def test_board_chat_run_http_route_requires_both_auth_layers(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.accept_socket_board_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/runs"
    body = {"task_id": str(uuid4()), "message": "hello"}

    assert client.post(path, json=body, headers={"Authorization": "Bearer user-token"}).status_code == 401
    assert client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 401
    response = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_uid": "run-uid",
        "status": "accepted",
        "accepted": True,
        "session": {"title": "Untitled", "uid": "session-uid"},
        "user_message": {"uid": "message-uid", "message": {"content": "hello"}, "chat_session_uid": "session-uid"},
    }
    assert (
        client.post(
            path,
            json={**body, "file_path": "/tmp/upload"},
            headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
        ).status_code
        == 400
    )
    service.internal_bot_run.accept_board_chat.assert_called_once()


def test_board_chat_start_requires_authorized_owner_and_claims_once(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "read"},
    )
    project_session = SimpleNamespace(id=SnowflakeID(5), get_uid=lambda: "session-uid")
    service.internal_bot_run.get_board_chat_context.return_value = (run, project_session, Mock())
    service.internal_bot_run.start_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: run_uid, attempt=1),
        {"session_id": "session-uid", "thread_id": "thread-id"},
        SimpleNamespace(api_response=lambda: {"uid": "ai-message-uid", "message": {"content": ""}}),
    )
    form = SocketBoardChatStartForm(active_document_names=[])

    response = SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, form, service)
    assert orjson.loads(response.body) == {
        "run_uid": run_uid,
        "attempt": 1,
        "graph_request": {"session_id": "session-uid", "thread_id": "thread-id"},
        "ai_message": {"uid": "ai-message-uid", "message": {"content": ""}, "chat_session_uid": "session-uid"},
    }
    assert service.internal_bot_run.start_board_chat.call_args.kwargs["lease_seconds"] == 150

    service.internal_bot_run.start_board_chat.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, form, service)

    run.user_id = SnowflakeID(99)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, form, service)


def test_board_chat_start_rechecks_removed_project_update_permission(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "edit"},
    )
    service.internal_bot_run.get_board_chat_context.return_value = (
        run,
        SimpleNamespace(id=SnowflakeID(5), get_uid=lambda: "session-uid"),
        Mock(),
    )
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Read.value]

    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.start_socket_board_chat_run(
            make_request(),
            PROJECT_UID,
            run_uid,
            SocketBoardChatStartForm(active_document_names=[]),
            service,
        )

    service.internal_bot_run.start_board_chat.assert_not_called()


def test_langflow_board_chat_run_accepts_and_starts_with_external_request(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    bot, _ = service.project.get_assigned_internal_bot_by_type.return_value
    bot.platform = BotPlatform.Langflow
    bot.platform_running_type = BotPlatformRunningType.Endpoint

    accepted = SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, make_form(), service)
    assert orjson.loads(accepted.body)["status"] == "accepted"

    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=bot.id,
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
    )
    service.internal_bot_run.get_board_chat_context.return_value = (
        run,
        SimpleNamespace(id=SnowflakeID(5), get_uid=lambda: "session-uid"),
        Mock(),
    )
    external_request = {
        "session_id": "session-uid",
        "thread_id": "thread-id",
        "url": "https://langflow.example.test/api/v1/run/flow?stream=true",
        "api_key": "server-only-key",
        "request_body": {"session_id": "session-uid", "input_value": "hello"},
    }
    service.internal_bot_run.start_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: run_uid, attempt=1),
        external_request,
        SimpleNamespace(api_response=lambda: {"uid": "ai-message-uid"}),
    )

    started = SocketAuthApi.start_socket_board_chat_run(
        make_request(), PROJECT_UID, run_uid, SocketBoardChatStartForm(active_document_names=[]), service
    )
    body = orjson.loads(started.body)
    assert body["langflow_request"] == external_request
    assert "graph_request" not in body

    bot.platform = BotPlatform.N8N
    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.accept_socket_board_chat_run(make_request(), PROJECT_UID, make_form(), service)


def test_accepted_board_chat_scan_requires_internal_secret_without_user_bearer(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run = InternalBotRun.model_construct(
        id=SnowflakeID(6), project_id=SnowflakeID(2), scope_table="card", scope_uid=CARD_UID
    )
    service.internal_bot_run.list_accepted_board_chat_runs.return_value = [run]

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.list_accepted_socket_board_chat_runs(make_request(secret="wrong", bearer=None), 10, service)
    service.internal_bot_run.list_accepted_board_chat_runs.assert_not_called()

    response = SocketAuthApi.list_accepted_socket_board_chat_runs(make_request(bearer=None), 10, service)
    assert orjson.loads(response.body) == {
        "runs": [
            {
                "run_uid": run.get_uid(),
                "project_uid": PROJECT_UID,
                "scope_table": "card",
                "scope_uid": CARD_UID,
            }
        ]
    }
    service.internal_bot_run.list_accepted_board_chat_runs.assert_called_once_with(10, None)

    service.internal_bot_run.list_accepted_board_chat_runs.reset_mock()
    SocketAuthApi.list_accepted_socket_board_chat_runs(
        make_request(bearer=None), 10, service, after_run_uid=run.get_uid()
    )
    service.internal_bot_run.list_accepted_board_chat_runs.assert_called_once_with(10, run.id)


def test_accepted_board_chat_scan_http_route_parses_cursor_and_limit(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    service.internal_bot_run.list_accepted_board_chat_runs.return_value = []
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.list_accepted_socket_board_chat_runs
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = "/auth/socket/board/chat/runs/accepted"

    assert client.get(path, params={"limit": 10}).status_code == 401
    response = client.get(
        path,
        params={"limit": 10, "after_run_uid": SnowflakeID(6).to_short_code()},
        headers={"X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {"runs": []}
    service.internal_bot_run.list_accepted_board_chat_runs.assert_called_once_with(10, SnowflakeID(6))
    assert client.get(path, params={"limit": 101}, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 400


def test_recovered_board_chat_start_rechecks_user_membership_and_bot(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = InternalBotRun.model_construct(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
    )
    project_session = SimpleNamespace(get_uid=lambda: "session-uid")
    service.internal_bot_run.get_board_chat_run.return_value = run
    service.internal_bot_run.get_board_chat_context.return_value = (run, project_session, Mock())
    service.internal_bot_run.start_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: run_uid, attempt=1),
        {"session_id": "session-uid", "thread_id": "thread-id"},
        SimpleNamespace(api_response=lambda: {"uid": "ai-message-uid", "message": {"content": ""}}),
    )
    form = SocketBoardChatStartForm(active_document_names=[])

    response = SocketAuthApi.recover_start_socket_board_chat_run(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(response.body)["run_uid"] == run_uid
    service.internal_bot_run.start_board_chat.assert_called_once()

    service.internal_bot_run.start_board_chat.reset_mock()
    monkeypatch.setattr(SocketAuthApi.Auth, "get_user_by_id", lambda user_id: None)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.recover_start_socket_board_chat_run(
            make_request(bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.start_board_chat.assert_not_called()

    allow_user(monkeypatch)
    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: False)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.recover_start_socket_board_chat_run(
            make_request(bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.start_board_chat.assert_not_called()

    allow_user(monkeypatch)
    run.internal_bot_id = SnowflakeID(99)
    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.recover_start_socket_board_chat_run(
            make_request(bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.start_board_chat.assert_not_called()


def test_board_chat_start_rejects_missing_credentials_and_changed_bot(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(99),
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
    )
    service.internal_bot_run.get_board_chat_context.return_value = (
        run,
        SimpleNamespace(get_uid=lambda: "session-uid"),
        Mock(),
    )
    form = SocketBoardChatStartForm(active_document_names=[])

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.start_socket_board_chat_run(make_request(secret="wrong"), PROJECT_UID, run_uid, form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.start_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.start_board_chat.assert_not_called()

    with pytest.raises(ApiException.ServiceUnavailable_503):
        SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.start_board_chat.assert_not_called()


def test_board_chat_start_uses_card_context_and_rejects_cross_scope_documents(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        status=InternalBotRunStatus.Accepted,
        scope_table="card",
        scope_uid=CARD_UID,
    )
    service.internal_bot_run.get_board_chat_context.return_value = (run, Mock(), Mock())
    service.card.get_by_id_like.return_value = SimpleNamespace(project_id=SnowflakeID(2))
    service.project.get_user_role_actions_by_project.return_value = ["read"]
    monkeypatch.setattr(SocketAuthApi, "NativeCardWorkspaceAdapter", lambda user, service: Mock())
    bundle = SimpleNamespace(model_dump=lambda **kwargs: {"card_uid": CARD_UID, "card": {"title": "Current"}})
    monkeypatch.setattr(SocketAuthApi, "get_card_bundle", lambda *args: bundle)
    service.internal_bot_run.start_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: run_uid, attempt=1),
        {"session_id": "session-uid", "thread_id": "thread-id"},
        SimpleNamespace(api_response=lambda: {"uid": "ai-message-uid", "message": {"content": ""}}),
    )
    form = SocketBoardChatStartForm(
        active_document_names=[f"card:{CARD_UID}:description", f"card:{CARD_UID}:description"]
    )

    SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, form, service)
    kwargs = service.internal_bot_run.start_board_chat.call_args.kwargs
    assert kwargs["scope_context"] == {"card_uid": CARD_UID, "card": {"title": "Current"}}
    assert kwargs["active_collaborative_documents"] == [
        {
            "document_name": f"card:{CARD_UID}:description",
            "entity_uid": CARD_UID,
            "type": "card",
            "section": "description",
            "api_field": "description",
        }
    ]

    other_uid = SnowflakeID(99).to_short_code()
    foreign_form = SocketBoardChatStartForm(active_document_names=[f"card:{other_uid}:description"])
    service.internal_bot_run.start_board_chat.reset_mock()
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, foreign_form, service)
    service.internal_bot_run.start_board_chat.assert_not_called()

    invalid_form = SocketBoardChatStartForm(active_document_names=[f"card:{CARD_UID}:description:extra"])
    with pytest.raises(ApiException.BadRequest_400):
        SocketAuthApi.start_socket_board_chat_run(make_request(), PROJECT_UID, run_uid, invalid_form, service)
    service.internal_bot_run.start_board_chat.assert_not_called()


@pytest.mark.parametrize(
    ("document_type", "section", "expected"),
    [
        (EEditorCollaborationType.BoardColumnName, "column", {"api_field": "name", "field": "name"}),
        (EEditorCollaborationType.Card, "title", {"api_field": "title", "field": "title"}),
        (EEditorCollaborationType.Card, "description", {"api_field": "description"}),
        (EEditorCollaborationType.Card, "deadline", {"api_field": "deadline_at", "field": "value"}),
        (EEditorCollaborationType.Card, "members", {"api_field": "assigned_users", "field": "selected-member-uids"}),
        (EEditorCollaborationType.Card, "labels", {"api_field": "labels", "field": "selected-label-uids"}),
        (
            EEditorCollaborationType.Card,
            "relationships-parents",
            {"api_field": "relationships", "field": "selected-relationships"},
        ),
        (
            EEditorCollaborationType.Card,
            "relationships-children",
            {"api_field": "relationships", "field": "selected-relationships"},
        ),
        (EEditorCollaborationType.Card, "attachment-abc", {"api_field": "attachment_name", "field": "name"}),
        (EEditorCollaborationType.Card, "comment-abc", {"api_field": "content"}),
        (EEditorCollaborationType.Card, "checklist-abc", {"api_field": "title", "field": "title"}),
        (EEditorCollaborationType.Card, "checkitem-abc", {"api_field": "title", "field": "title"}),
        (EEditorCollaborationType.Card, "checkitem-abc-deadline", {"api_field": "deadline_at", "field": "value"}),
        (EEditorCollaborationType.Card, "metadata-abc", {"api_field": "metadata", "field": "key/value"}),
        (EEditorCollaborationType.Card, "unknown", {}),
        (EEditorCollaborationType.Wiki, "title", {"api_field": "title", "field": "title"}),
        (EEditorCollaborationType.Wiki, "content", {"api_field": "content"}),
        (
            EEditorCollaborationType.Wiki,
            "private-assignees",
            {"api_field": "assignees", "field": "selected-member-uids"},
        ),
        (EEditorCollaborationType.Wiki, "metadata-abc", {"api_field": "metadata", "field": "key/value"}),
        (EEditorCollaborationType.BotSchedule, "card-abc-schedule", {"api_field": "schedule", "field": "schedule"}),
    ],
)
def test_board_chat_document_schema_matches_existing_editor_fields(
    document_type: EEditorCollaborationType, section: str, expected: dict[str, str]
) -> None:
    assert SocketAuthApi._board_chat_document_schema(document_type, section) == expected


@pytest.mark.parametrize(
    ("scope_table", "document_names", "expected_types"),
    [
        (
            "card",
            [f"card:{CARD_UID}:labels", f"bot-schedule:{PROJECT_UID}:card-{CARD_UID}-daily"],
            ["card", "bot-schedule"],
        ),
        (
            "project_column",
            [
                f"board-column-name:{PROJECT_UID}:{CARD_UID}",
                f"bot-schedule:{PROJECT_UID}:project_column-{CARD_UID}-daily",
            ],
            ["board-column-name", "bot-schedule"],
        ),
        ("project_wiki", [f"wiki:{CARD_UID}:content"], ["wiki"]),
    ],
)
def test_board_chat_active_documents_match_scope(
    scope_table: str, document_names: list[str], expected_types: list[str]
) -> None:
    run = InternalBotRun(
        request_key="scope-test",
        request_digest="scope-test",
        client_task_id="scope-test",
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        kind=InternalBotRunKind.BoardChat,
        scope_table=scope_table,
        scope_uid=CARD_UID,
    )
    form = SocketBoardChatStartForm(active_document_names=document_names)
    documents = SocketAuthApi._board_chat_active_documents(form, run, PROJECT_UID)
    assert [document["document_name"] for document in documents] == document_names
    assert [document["type"] for document in documents] == expected_types

    wrong_schedule = SocketBoardChatStartForm(
        active_document_names=[f"bot-schedule:{PROJECT_UID}:card-{SnowflakeID(99).to_short_code()}-daily"]
    )
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi._board_chat_active_documents(wrong_schedule, run, PROJECT_UID)


def test_board_chat_start_accepts_only_bounded_document_names() -> None:
    with pytest.raises(ValidationError):
        SocketBoardChatStartForm.model_validate(
            {"active_document_names": [{"document_name": f"card:{CARD_UID}:description", "api_field": "title"}]}
        )
    with pytest.raises(ValidationError):
        SocketBoardChatStartForm(active_document_names=["x" * 513])
    with pytest.raises(ValidationError):
        SocketBoardChatStartForm(active_document_names=[f"card:{CARD_UID}:description"] * 129)


def test_board_chat_start_http_route_keeps_graph_request_internal(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        id=SnowflakeID(6),
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        status=InternalBotRunStatus.Accepted,
        scope_table="project",
        scope_uid=None,
    )
    service.internal_bot_run.get_board_chat_context.return_value = (
        run,
        SimpleNamespace(get_uid=lambda: "session-uid"),
        Mock(),
    )
    service.internal_bot_run.start_board_chat.return_value = (
        SimpleNamespace(get_uid=lambda: run_uid, attempt=1),
        {"session_id": "session-uid", "thread_id": "thread-id", "tweaks": {"app_api_token": "private"}},
        SimpleNamespace(api_response=lambda: {"uid": "ai-message-uid", "message": {"content": ""}}),
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.start_socket_board_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/runs/{run_uid}/start"
    body = {"active_document_names": []}

    assert client.post(path, json=body, headers={"Authorization": "Bearer user-token"}).status_code == 401
    assert client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 401
    service.internal_bot_run.start_board_chat.assert_not_called()

    response = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json()["graph_request"]["tweaks"]["app_api_token"] == "private"
    service.internal_bot_run.start_board_chat.assert_called_once()


def test_board_chat_cancel_requires_owner_membership_and_internal_auth(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    task_id = uuid4()
    form = SocketBoardChatCancelForm(task_id=task_id)
    service.internal_bot_run.cancel_board_chat.return_value = SimpleNamespace(
        get_uid=lambda: "run-uid",
        status=InternalBotRunStatus.Cancelled,
        client_task_id=str(task_id),
        request_payload={},
    )

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.cancel_socket_board_chat_run(make_request(secret="wrong"), PROJECT_UID, form, service)
    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.cancel_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, form, service)
    service.internal_bot_run.cancel_board_chat.assert_not_called()

    response = SocketAuthApi.cancel_socket_board_chat_run(make_request(), PROJECT_UID, form, service)
    assert orjson.loads(response.body) == {
        "run_uid": "run-uid",
        "status": "cancelled",
        "task_id": str(task_id),
    }
    service.internal_bot_run.cancel_board_chat.assert_called_once_with(task_id, SnowflakeID(1), SnowflakeID(2))

    service.internal_bot_run.cancel_board_chat.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.cancel_socket_board_chat_run(make_request(), PROJECT_UID, form, service)

    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: False)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.cancel_socket_board_chat_run(make_request(), PROJECT_UID, form, service)

    with pytest.raises(ValidationError):
        SocketBoardChatCancelForm.model_validate({"task_id": str(task_id), "project_uid": PROJECT_UID})


def test_terminal_board_chat_attachment_cleanup_retries_from_the_durable_run(monkeypatch: MonkeyPatch) -> None:
    service = make_service()
    bot = SimpleNamespace()
    run = InternalBotRun(
        request_key="attachment-cleanup",
        request_digest="attachment-cleanup",
        client_task_id="attachment-cleanup",
        user_id=SnowflakeID(1),
        project_id=SnowflakeID(2),
        internal_bot_id=SnowflakeID(3),
        kind=InternalBotRunKind.BoardChat,
        request_payload={"attachment": {"file_id": "file-id", "token": "opaque-token"}},
    )
    service.internal_bot.get_by_id_like.return_value = bot
    delete_external = Mock(return_value=False)
    delete_ticket = Mock()
    schedule_reconciliation = Mock()
    monkeypatch.setattr(SocketAuthApi.LangflowFileClient, "delete", delete_external)
    monkeypatch.setattr(SocketAuthApi, "delete_board_chat_attachment_ticket", delete_ticket)
    monkeypatch.setattr(
        SocketAuthApi,
        "schedule_board_chat_attachment_reconciliation",
        schedule_reconciliation,
    )

    SocketAuthApi._cleanup_board_chat_attachment(service, run, delete_external=True)

    delete_external.assert_called_once_with(bot, "file-id")
    schedule_reconciliation.assert_called_once_with(run.get_uid())
    delete_ticket.assert_not_called()


def test_board_chat_cancel_http_route_requires_both_auth_layers(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    task_id = uuid4()
    service.internal_bot_run.cancel_board_chat.return_value = SimpleNamespace(
        get_uid=lambda: "run-uid",
        status=InternalBotRunStatus.Cancelled,
        client_task_id=str(task_id),
        request_payload={},
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.cancel_socket_board_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/cancel"
    body = {"task_id": str(task_id)}

    assert client.post(path, json=body, headers={"Authorization": "Bearer user-token"}).status_code == 401
    assert client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 401
    response = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {"run_uid": "run-uid", "status": "cancelled", "task_id": str(task_id)}
    service.internal_bot_run.cancel_board_chat.assert_called_once_with(task_id, SnowflakeID(1), SnowflakeID(2))


def test_board_chat_finish_requires_internal_secret_and_matching_run(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2), request_payload={}
    )
    service.internal_bot_run.finish_board_chat.return_value = True
    form = SocketBoardChatFinishForm(attempt=1, status="completed", output_text="Graph answer")

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.finish_socket_board_chat_run(
            make_request(secret="wrong", bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.finish_board_chat.assert_not_called()

    response = SocketAuthApi.finish_socket_board_chat_run(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(response.body) == {"run_uid": run_uid, "attempt": 1, "status": "completed"}
    service.internal_bot_run.finish_board_chat.assert_called_once_with(
        SnowflakeID(6), 1, InternalBotRunStatus.Completed, "Graph answer", None
    )

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.finish_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.finish_board_chat.assert_called_once()

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2), request_payload={}
    )
    service.internal_bot_run.finish_board_chat.return_value = False
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.finish_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)


def test_board_chat_finish_http_route_needs_secret_but_not_user_bearer(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2), request_payload={}
    )
    service.internal_bot_run.finish_board_chat.return_value = True
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.finish_socket_board_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/runs/{run_uid}/finish"
    body = {"attempt": 1, "status": "completed", "output_text": "Graph answer"}

    assert client.post(path, json=body).status_code == 401
    assert (
        client.post(
            path, json={**body, "status": "streaming"}, headers={"X-Socket-Internal-Secret": "s" * 32}
        ).status_code
        == 400
    )
    service.internal_bot_run.finish_board_chat.assert_not_called()

    response = client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32})
    assert response.status_code == 200
    assert response.json() == {"run_uid": run_uid, "attempt": 1, "status": "completed"}
    service.internal_bot_run.finish_board_chat.assert_called_once()


def test_board_chat_lease_renews_only_current_project_and_attempt(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        status=InternalBotRunStatus.Streaming,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "read"},
    )
    service.internal_bot_run.renew_board_chat_lease.return_value = True
    form = SocketBoardChatLeaseForm(attempt=1)

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.renew_socket_board_chat_run_lease(
            make_request(secret="wrong", bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.renew_board_chat_lease.assert_not_called()

    response = SocketAuthApi.renew_socket_board_chat_run_lease(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(response.body) == {"run_uid": run_uid, "attempt": 1, "status": "streaming"}
    service.internal_bot_run.renew_board_chat_lease.assert_called_once_with(SnowflakeID(6), 1, 150)

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(99), status=InternalBotRunStatus.Streaming
    )
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_board_chat_run_lease(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.renew_board_chat_lease.assert_called_once()

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        status=InternalBotRunStatus.Streaming,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "read"},
    )
    service.internal_bot_run.renew_board_chat_lease.return_value = False
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.renew_socket_board_chat_run_lease(make_request(bearer=None), PROJECT_UID, run_uid, form, service)

    service.internal_bot_run.renew_board_chat_lease.return_value = True
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        status=InternalBotRunStatus.Resuming,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "read"},
    )
    resumed = SocketAuthApi.renew_socket_board_chat_run_lease(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(resumed.body)["status"] == "resuming"

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        status=InternalBotRunStatus.Completed,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "read"},
    )
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.renew_socket_board_chat_run_lease(make_request(bearer=None), PROJECT_UID, run_uid, form, service)


def test_board_chat_lease_rechecks_membership_and_requested_permission(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    run = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        status=InternalBotRunStatus.Streaming,
        scope_table="project",
        scope_uid=None,
        request_payload={"api_permission_level": "edit"},
    )
    service.internal_bot_run.get_board_chat_run.return_value = run
    service.internal_bot_run.renew_board_chat_lease.return_value = True
    service.project.get_user_role_actions_by_project.return_value = [
        ProjectRoleAction.Read.value,
        ProjectRoleAction.Update.value,
    ]
    form = SocketBoardChatLeaseForm(attempt=1)

    response = SocketAuthApi.renew_socket_board_chat_run_lease(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(response.body)["status"] == "streaming"

    service.internal_bot_run.renew_board_chat_lease.reset_mock()
    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: False)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_board_chat_run_lease(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.renew_board_chat_lease.assert_not_called()

    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: True)
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Read.value]
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.renew_socket_board_chat_run_lease(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    service.internal_bot_run.renew_board_chat_lease.assert_not_called()


def test_board_chat_pause_requires_internal_secret_and_publishes_only_new_approval(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    published = Mock()
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "requested", published)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(project_id=SnowflakeID(2))
    approval = SimpleNamespace(get_uid=lambda: "approval-uid")
    interrupt = {"id": "graph-interrupt", "value": {"type": "approval_request"}}
    saved = {"id": "graph-interrupt", "value": {"type": "approval_request", "approval_uid": "approval-uid"}}
    form = SocketBoardChatPauseForm(attempt=1, output_text="Partial answer", interrupt=interrupt)
    service.internal_bot_run.pause_board_chat.return_value = (saved, approval)
    service.graph_approval_request.get_api_response.return_value = {"uid": "approval-uid"}

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.pause_socket_board_chat_run(
            make_request(secret="wrong", bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.pause_board_chat.assert_not_called()

    response = SocketAuthApi.pause_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    assert orjson.loads(response.body) == {
        "run_uid": run_uid,
        "attempt": 1,
        "status": "awaiting_approval",
        "interrupt": saved,
    }
    published.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "approval-uid"})

    service.internal_bot_run.pause_board_chat.return_value = (saved, None)
    SocketAuthApi.pause_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    published.assert_called_once()

    service.internal_bot_run.pause_board_chat.return_value = (saved, approval)
    published.side_effect = RuntimeError("Broker unavailable")
    response = SocketAuthApi.pause_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    assert orjson.loads(response.body)["status"] == "awaiting_approval"

    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(project_id=SnowflakeID(99))
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.pause_socket_board_chat_run(make_request(bearer=None), PROJECT_UID, run_uid, form, service)


def test_board_chat_pause_http_route_requires_secret(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(project_id=SnowflakeID(2))
    service.internal_bot_run.pause_board_chat.return_value = ({"type": "instruction_request"}, None)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.pause_socket_board_chat_run
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/runs/{run_uid}/pause"
    body = {"attempt": 1, "output_text": "", "interrupt": {"type": "instruction_request"}}

    assert client.post(path, json=body).status_code == 401
    service.internal_bot_run.pause_board_chat.assert_not_called()
    response = client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32})
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_approval"


def test_board_chat_resume_claim_requires_owner_role_and_matching_run(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "create_bot_one_time_token", lambda *args: "private-graph-token")
    service = make_service()
    session_uid = SnowflakeID(5).to_short_code()
    message_uid = SnowflakeID(7).to_short_code()
    approval_uid = SnowflakeID(8).to_short_code()
    session = SimpleNamespace(id=SnowflakeID(6), user_id=SnowflakeID(1))
    service.chat.get_session_by_filterable.return_value = (session, Mock())
    run = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        chat_session_id=session.id,
        scope_table="project",
        scope_uid=None,
        graph_thread_id="graph-thread",
        graph_session_id=session_uid,
        attempt=2,
        get_uid=lambda: "run-uid",
    )
    service.internal_bot_run.get_board_chat_run_by_ai_message.return_value = run
    service.internal_bot_run.claim_board_chat_resume.return_value = run
    service.project.get_user_role_actions_by_project.return_value = ["update"]
    form = SocketBoardChatResumeClaimForm(
        message_uid=message_uid,
        thread_id="graph-thread",
        session_id=session_uid,
        approval_uid=approval_uid,
        resume=SocketBoardChatResumeDecision(approved=True, rejected=False),
    )

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.claim_socket_board_chat_resume(make_request(secret="wrong"), PROJECT_UID, form, service)
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()

    response = SocketAuthApi.claim_socket_board_chat_resume(make_request(), PROJECT_UID, form, service)
    body = orjson.loads(response.body)
    assert body == {
        "run_uid": "run-uid",
        "attempt": 2,
        "thread_id": "graph-thread",
        "session_id": session_uid,
        "resume": {
            "approved": True,
            "rejected": False,
            "app_api_token": "private-graph-token",
            "api_permission_level": "full_access",
            "api_approval_policy": {"read": "allow", "create": "allow", "edit": "allow", "delete": "allow"},
        },
    }
    claim_args = service.internal_bot_run.claim_board_chat_resume.call_args.args
    assert claim_args[:6] == (
        SnowflakeID(2),
        SnowflakeID(1),
        SnowflakeID(7),
        "graph-thread",
        session_uid,
        SnowflakeID(8),
    )
    assert claim_args[6] == {"approved": True, "rejected": False}
    assert "app_api_token" not in claim_args[6]

    service.project.get_user_role_actions_by_project.return_value = ["read"]
    service.internal_bot_run.claim_board_chat_resume.reset_mock()
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.claim_socket_board_chat_resume(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()

    service.project.get_user_role_actions_by_project.return_value = ["update"]
    service.internal_bot_run.claim_board_chat_resume.return_value = None
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.claim_socket_board_chat_resume(make_request(), PROJECT_UID, form, service)

    service.internal_bot_run.get_board_chat_run_by_ai_message.return_value = SimpleNamespace(
        **{**vars(run), "project_id": SnowflakeID(99)}
    )
    service.internal_bot_run.claim_board_chat_resume.reset_mock()
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.claim_socket_board_chat_resume(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()

    service.internal_bot_run.get_board_chat_run_by_ai_message.return_value = run

    def fail_token(*_args: object) -> str:
        raise RuntimeError("Token service unavailable")

    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "create_bot_one_time_token", fail_token)
    with pytest.raises(RuntimeError, match="Token service unavailable"):
        SocketAuthApi.claim_socket_board_chat_resume(make_request(), PROJECT_UID, form, service)
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()


@pytest.mark.parametrize(
    "decision",
    [
        {"approved": True, "rejected": True},
        {"approved": False, "rejected": False},
        {"approved": True, "rejected": False, "app_api_token": "forged"},
        {"approved": True, "rejected": False, "instruction": "extra"},
        {"approved": False, "rejected": False, "instruction": "  "},
    ],
)
def test_board_chat_resume_rejects_invalid_decisions(decision: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SocketBoardChatResumeClaimForm.model_validate(
            {
                "message_uid": SnowflakeID(7).to_short_code(),
                "thread_id": "graph-thread",
                "session_id": SnowflakeID(5).to_short_code(),
                "resume": decision,
            }
        )


def test_board_chat_resume_claim_http_route_requires_secret_and_bearer(monkeypatch: MonkeyPatch) -> None:
    allow_user(monkeypatch)
    service = make_service()
    session_uid = SnowflakeID(5).to_short_code()
    message_uid = SnowflakeID(7).to_short_code()
    session = SimpleNamespace(id=SnowflakeID(6), user_id=SnowflakeID(1))
    service.chat.get_session_by_filterable.return_value = (session, Mock())
    run = SimpleNamespace(
        project_id=SnowflakeID(2),
        user_id=SnowflakeID(1),
        chat_session_id=session.id,
        scope_table="project",
        scope_uid=None,
        graph_thread_id="graph-thread",
        graph_session_id=session_uid,
        attempt=2,
        get_uid=lambda: "run-uid",
    )
    service.internal_bot_run.get_board_chat_run_by_ai_message.return_value = run
    service.internal_bot_run.claim_board_chat_resume.return_value = run
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is SocketAuthApi.claim_socket_board_chat_resume
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/{PROJECT_UID}/chat/resume/claim"
    body = {
        "message_uid": message_uid,
        "thread_id": "graph-thread",
        "session_id": session_uid,
        "resume": {"approved": False, "rejected": False, "instruction": "Use a different approach"},
    }

    assert client.post(path, json=body, headers={"Authorization": "Bearer user-token"}).status_code == 401
    assert client.post(path, json=body, headers={"X-Socket-Internal-Secret": "s" * 32}).status_code == 401
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()
    assert (
        client.post(
            path,
            json={
                **body,
                "resume": {
                    "approved": False,
                    "rejected": False,
                    "instruction": "Use a different approach",
                    "app_api_token": "forged",
                },
            },
            headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
        ).status_code
        == 400
    )
    service.internal_bot_run.claim_board_chat_resume.assert_not_called()

    response = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer user-token", "X-Socket-Internal-Secret": "s" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_uid": "run-uid",
        "attempt": 2,
        "thread_id": "graph-thread",
        "session_id": session_uid,
        "resume": body["resume"],
    }


def test_board_chat_resume_result_publishes_only_new_persisted_approvals(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    updated = Mock()
    requested = Mock()
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "updated", updated)
    monkeypatch.setattr(SocketAuthApi.GraphApprovalPublisher, "requested", requested)
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    session_uid = SnowflakeID(5).to_short_code()
    run = SimpleNamespace(project_id=SnowflakeID(2), graph_thread_id="graph-thread", graph_session_id=session_uid)
    service.internal_bot_run.get_board_chat_run.return_value = run
    resolved = Mock()
    requested_approval = Mock()
    original = SimpleNamespace(api_response=lambda: {"uid": "original-uid", "message": {"content": "Partial"}})
    resumed = SimpleNamespace(api_response=lambda: {"uid": "resumed-uid", "message": {"content": "Done"}})
    saved_run = SimpleNamespace(status=InternalBotRunStatus.AwaitingApproval)
    service.internal_bot_run.complete_board_chat_resume.return_value = (
        saved_run,
        original,
        resumed,
        resolved,
        requested_approval,
        True,
    )
    service.graph_approval_request.get_api_response.side_effect = [
        {"uid": "resolved-approval"},
        {"uid": "new-approval"},
    ]
    form = SocketBoardChatResumeResultForm(
        attempt=2,
        thread_id="graph-thread",
        session_id=session_uid,
        response_text="Done",
        interrupt={"id": "next", "value": {"type": "approval_request"}},
    )

    with pytest.raises(ApiException.Unauthorized_401):
        SocketAuthApi.complete_socket_board_chat_resume(
            make_request(secret="wrong", bearer=None), PROJECT_UID, run_uid, form, service
        )
    service.internal_bot_run.complete_board_chat_resume.assert_not_called()

    response = SocketAuthApi.complete_socket_board_chat_resume(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(response.body) == {
        "run_uid": run_uid,
        "attempt": 2,
        "status": "awaiting_approval",
        "newly_applied": True,
        "original_message": {"uid": "original-uid", "message": {"content": "Partial"}, "chat_session_uid": session_uid},
        "resumed_message": {"uid": "resumed-uid", "message": {"content": "Done"}, "chat_session_uid": session_uid},
    }
    updated.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "resolved-approval"})
    requested.assert_called_once_with(service.project.get_by_id_like.return_value, {"uid": "new-approval"})

    service.internal_bot_run.complete_board_chat_resume.return_value = (saved_run, original, resumed, None, None, False)
    duplicate = SocketAuthApi.complete_socket_board_chat_resume(
        make_request(bearer=None), PROJECT_UID, run_uid, form, service
    )
    assert orjson.loads(duplicate.body)["newly_applied"] is False
    updated.assert_called_once()
    requested.assert_called_once()

    run.graph_thread_id = "other-thread"
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.complete_socket_board_chat_resume(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
    run.graph_thread_id = "graph-thread"
    run.project_id = SnowflakeID(99)
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.complete_socket_board_chat_resume(make_request(bearer=None), PROJECT_UID, run_uid, form, service)


def test_board_chat_resume_result_rejects_stale_attempt(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "Env", SimpleNamespace(SOCKET_PHOENIX_INTERNAL_SECRET="s" * 32))
    service = make_service()
    run_uid = SnowflakeID(6).to_short_code()
    session_uid = SnowflakeID(5).to_short_code()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        project_id=SnowflakeID(2), graph_thread_id="graph-thread", graph_session_id=session_uid
    )
    service.internal_bot_run.complete_board_chat_resume.return_value = None
    form = SocketBoardChatResumeResultForm(
        attempt=1, thread_id="graph-thread", session_id=session_uid, response_text="Late"
    )
    with pytest.raises(ApiException.Conflict_409):
        SocketAuthApi.complete_socket_board_chat_resume(make_request(bearer=None), PROJECT_UID, run_uid, form, service)
