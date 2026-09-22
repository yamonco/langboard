from time import time
from typing import Literal
from unittest.mock import Mock
import orjson
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jwt import ExpiredSignatureError, InvalidTokenError
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.auth import SocketAuthorization
from langboard.routes.auth.forms import (
    SocketChatResumeAuthorizationForm,
    SocketEditorAiAuthorizationForm,
    SocketEditorDocumentAuthorizationForm,
    SocketEditorDocumentsAuthorizationForm,
    SocketSubscriptionAuthorizationForm,
    SocketSubscriptionAuthorizationItem,
)
from langboard.routes.auth.SocketAuthApi import (
    SOCKET_INTERNAL_API_CONTRACT_VERSION,
    authenticate_socket,
    authorize_socket_editor_ai,
    authorize_socket_editor_document,
    authorize_socket_editor_http_document,
    authorize_socket_editor_http_documents,
    authorize_socket_project_chat_resume,
    authorize_socket_project_chat_session,
    authorize_socket_subscriptions,
    get_socket_capabilities,
)
from langboard.routes.auth.SocketAuthorization import (
    editor_document_subscription as _editor_document_subscription,
)
from langboard.routes.auth.SocketAuthorization import (
    is_editor_document_write_authorized as _is_editor_document_write_authorized,
)
from langboard.routes.auth.SocketAuthorization import (
    is_subscription_authorized as _is_subscription_authorized,
)
from langboard_shared.core.db import ChatContentModel
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, SettingSocketTopicID, SocketTopic
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    ApiKeyRole,
    Card,
    ChatGraphApprovalRequest,
    ChatHistory,
    ChatSession,
    GraphApprovalRequest,
    McpRole,
    Project,
    ProjectChatSession,
    ProjectWiki,
    SettingRole,
    User,
)
from langboard_shared.domain.models.ApiKeyRole import ApiKeyRoleAction
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from langboard_shared.domain.models.InternalBotRun import InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.GraphApprovalRequestService import GraphApprovalRequestService
from langboard_shared.Env import Env
from langboard_shared.helpers.AgentApiPermissionHelper import get_agent_allowed_permissions
from langboard_shared.infrastructure.repositories import Repository
from pydantic import ValidationError
from pytest import MonkeyPatch
from starlette.datastructures import Headers


def create_request(authorization: str | None) -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "headers": headers})


def create_internal_request(secret: str) -> Request:
    return Request({"type": "http", "headers": [(b"x-socket-internal-secret", secret.encode())]})


def create_user(
    *,
    user_id: int = 1,
    email: str = "user@example.com",
    is_admin: bool = False,
    activated: bool = True,
    deleted: bool = False,
) -> User:
    now = SafeDateTime.now()
    return User.model_construct(
        id=SnowflakeID(user_id),
        firstname="Test",
        lastname="User",
        email=email,
        is_admin=is_admin,
        activated_at=now if activated else None,
        deleted_at=now if deleted else None,
    )


def create_authorization_service() -> Mock:
    return Mock(spec=DomainService)


@pytest.mark.parametrize(
    ("permission_level", "expected_permissions"),
    [
        ("read", {"read"}),
        ("edit", {"read", "create", "edit"}),
        ("full_access", {"read", "create", "edit", "delete"}),
    ],
)
def test_bot_one_time_token_matches_api_permission_scope(
    permission_level: Literal["read", "edit", "full_access"], expected_permissions: set[str]
) -> None:
    before = time()
    token = AuthSecurity.create_bot_one_time_token(7, permission_level)
    payload = AuthSecurity.decode_access_token(token)

    assert payload["sub"] == "7"
    assert payload["internal"] == "bot"
    assert payload["api_permission_level"] == permission_level
    assert payload["iss"] == Env.PROJECT_NAME
    assert before + 299 <= payload["exp"] <= time() + 300
    assert get_agent_allowed_permissions(Headers({"X-Api-Token": token})) == expected_permissions


def test_bot_one_time_token_rejects_invalid_owner() -> None:
    with pytest.raises(ValueError):
        AuthSecurity.create_bot_one_time_token(0)


def test_socket_auth_returns_only_user_uid(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    monkeypatch.setattr(
        authenticate_socket.__globals__["AuthSecurity"],
        "decode_access_token",
        lambda token: {"sub": "1"},
    )
    monkeypatch.setattr(authenticate_socket.__globals__["Auth"], "get_user_by_id", lambda user_id: user)

    response = authenticate_socket(create_request("Bearer access-token"))

    assert orjson.loads(response.body) == {"user_uid": user.get_uid()}


def test_socket_capabilities_require_internal_auth_and_report_contract_version(monkeypatch: MonkeyPatch) -> None:
    secret = "s" * 32
    monkeypatch.setitem(
        get_socket_capabilities.__globals__,
        "Env",
        Mock(SOCKET_PHOENIX_INTERNAL_SECRET=secret),
    )

    response = get_socket_capabilities(create_internal_request(secret))

    assert orjson.loads(response.body) == {
        "contract_version": SOCKET_INTERNAL_API_CONTRACT_VERSION,
    }

    with pytest.raises(ApiException.Unauthorized_401):
        get_socket_capabilities(create_internal_request("wrong-secret"))

    monkeypatch.setitem(
        get_socket_capabilities.__globals__,
        "Env",
        Mock(SOCKET_PHOENIX_INTERNAL_SECRET=""),
    )
    with pytest.raises(ApiException.ServiceUnavailable_503):
        get_socket_capabilities(create_internal_request(secret))


@pytest.mark.parametrize("authorization", [None, "", "Basic token", "Bearer", "Bearer "])
def test_socket_auth_rejects_invalid_authorization_header(authorization: str | None) -> None:
    with pytest.raises(ApiException.Unauthorized_401):
        authenticate_socket(create_request(authorization))


@pytest.mark.parametrize(
    ("payload", "user"),
    [
        ({"sub": "1", "internal": "bot"}, create_user()),
        ({"sub": "1"}, create_user(activated=False)),
        ({"sub": "1"}, create_user(deleted=True)),
        ({"sub": "1"}, None),
    ],
)
def test_socket_auth_rejects_ineligible_users(
    monkeypatch: MonkeyPatch, payload: dict[str, str], user: User | None
) -> None:
    monkeypatch.setattr(authenticate_socket.__globals__["AuthSecurity"], "decode_access_token", lambda token: payload)
    monkeypatch.setattr(authenticate_socket.__globals__["Auth"], "get_user_by_id", lambda user_id: user)

    with pytest.raises(ApiException.Unauthorized_401):
        authenticate_socket(create_request("Bearer access-token"))


def test_socket_auth_rejects_invalid_token(monkeypatch: MonkeyPatch) -> None:
    def decode_access_token(token: str) -> dict[str, str]:
        raise InvalidTokenError("invalid")

    monkeypatch.setattr(
        authenticate_socket.__globals__["AuthSecurity"],
        "decode_access_token",
        decode_access_token,
    )

    with pytest.raises(ApiException.Unauthorized_401):
        authenticate_socket(create_request("Bearer invalid-token"))


def test_socket_auth_expiry_keeps_401_with_refresh_error_code(monkeypatch: MonkeyPatch) -> None:
    def decode_access_token(token: str) -> dict[str, str]:
        raise ExpiredSignatureError("expired")

    monkeypatch.setattr(AuthSecurity, "decode_access_token", decode_access_token)
    app = FastAPI()
    app.include_router(AppRouter.api)
    with TestClient(app) as client:
        for path, body in [("/auth/socket", None), ("/auth/socket/subscriptions", {"subscriptions": []})]:
            response = client.post(path, headers={"Authorization": "Bearer expired-token"}, json=body)
            assert response.status_code == 401
            assert response.json() == ApiErrorCode.AU1004.to_dict()


def test_socket_subscription_authorization_returns_only_allowed_items(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    form = SocketSubscriptionAuthorizationForm(
        subscriptions=[
            SocketSubscriptionAuthorizationItem(topic=SocketTopic.Board, topic_id="allowed"),
            SocketSubscriptionAuthorizationItem(topic=SocketTopic.Board, topic_id="denied"),
        ]
    )
    monkeypatch.setitem(
        authorize_socket_subscriptions.__globals__,
        "_authenticate_socket_user",
        lambda request: user,
    )
    monkeypatch.setitem(
        authorize_socket_subscriptions.__globals__,
        "is_subscription_authorized",
        lambda service, current_user, topic, topic_id: topic_id == "allowed",
    )

    response = authorize_socket_subscriptions(
        create_request("Bearer access-token"), form, create_authorization_service()
    )

    assert orjson.loads(response.body) == {"authorized": [{"topic": SocketTopic.Board.value, "topic_id": "allowed"}]}


def test_socket_chat_session_authorization_requires_project_and_owner(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = create_authorization_service()
    project_uid = SnowflakeID(2).to_short_code()
    session_uid = SnowflakeID(3).to_short_code()
    monkeypatch.setitem(
        authorize_socket_project_chat_session.__globals__, "_authenticate_socket_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_session.__globals__,
        "is_subscription_authorized",
        lambda current_service, current_user, topic, topic_id: current_service is service
        and current_user is user
        and topic == SocketTopic.Board
        and topic_id == project_uid,
    )
    service.chat.get_session_by_filterable.return_value = (Mock(user_id=user.id), Mock())

    response = authorize_socket_project_chat_session(
        create_request("Bearer access-token"), project_uid, session_uid, service
    )

    assert orjson.loads(response.body) == {}
    service.chat.get_session_by_filterable.assert_called_once_with(ProjectChatSession, SnowflakeID(3), project_uid)

    service.chat.get_session_by_filterable.return_value = (Mock(user_id=SnowflakeID(4)), Mock())
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_session(create_request("Bearer access-token"), project_uid, session_uid, service)

    service.chat.get_session_by_filterable.return_value = None
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_session(create_request("Bearer access-token"), project_uid, session_uid, service)

    service.chat.get_session_by_filterable.reset_mock()
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_session(
            create_request("Bearer access-token"), "other-project", session_uid, service
        )
    service.chat.get_session_by_filterable.assert_not_called()


@pytest.mark.parametrize("session_uid", ["", "invalid", "!!!!!!!!!!!"])
def test_socket_chat_session_authorization_rejects_invalid_uid(monkeypatch: MonkeyPatch, session_uid: str) -> None:
    user = create_user()
    service = create_authorization_service()
    monkeypatch.setitem(
        authorize_socket_project_chat_session.__globals__, "_authenticate_socket_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_session.__globals__, "is_subscription_authorized", lambda *args: True
    )

    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_session(create_request("Bearer access-token"), "project", session_uid, service)
    service.chat.get_session_by_filterable.assert_not_called()


def test_socket_chat_session_authorization_requires_bearer_token() -> None:
    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_project_chat_session(
            create_request(None), "project", "session", create_authorization_service()
        )


def test_socket_chat_resume_matches_saved_interrupt_and_pending_approval(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = create_authorization_service()
    session = ChatSession.model_construct(id=SnowflakeID(3), user_id=user.id)
    message = ChatHistory.model_construct(
        id=SnowflakeID(4),
        chat_session_id=session.id,
        is_received=True,
        message=ChatContentModel(
            content="",
            graph_interrupt={
                "value": {
                    "type": "approval_request",
                    "thread_id": "thread-1",
                    "session_id": "graph-session-1",
                    "approval_uid": SnowflakeID(5).to_short_code(),
                }
            },
        ),
    )
    form = SocketChatResumeAuthorizationForm(
        message_uid=message.get_uid(),
        thread_id="thread-1",
        session_id="graph-session-1",
        approval_uid=SnowflakeID(5).to_short_code(),
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_resume.__globals__, "_authenticate_socket_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_resume.__globals__, "is_subscription_authorized", lambda *args: True
    )
    service.chat.get_session_by_filterable.return_value = (session, Mock())
    service.chat.get_history_by_id_like.return_value = message
    service.graph_approval_request.is_pending_chat_resume.return_value = True
    request = create_request("Bearer access-token")

    response = authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)

    assert orjson.loads(response.body) == {}
    service.graph_approval_request.is_pending_chat_resume.assert_called_once_with(
        SnowflakeID(5), session, message, "thread-1"
    )

    for invalid_form in (
        form.model_copy(update={"thread_id": "other-thread"}),
        form.model_copy(update={"session_id": "other-session"}),
        form.model_copy(update={"approval_uid": SnowflakeID(6).to_short_code()}),
    ):
        with pytest.raises(ApiException.Forbidden_403):
            authorize_socket_project_chat_resume(request, "project", session.get_uid(), invalid_form, service)

    service.graph_approval_request.is_pending_chat_resume.return_value = False
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)

    service.chat.get_history_by_id_like.return_value = message.model_copy(update={"chat_session_id": SnowflakeID(7)})
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)


def test_socket_chat_resume_rejects_resolved_and_unbound_interrupts(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = create_authorization_service()
    session = ChatSession.model_construct(id=SnowflakeID(3), user_id=user.id)
    message = ChatHistory.model_construct(
        id=SnowflakeID(4),
        chat_session_id=session.id,
        is_received=True,
        message=ChatContentModel(content="", graph_interrupt={"thread_id": "thread-1", "status": "resolved"}),
    )
    form = SocketChatResumeAuthorizationForm(message_uid=message.get_uid(), thread_id="thread-1")
    monkeypatch.setitem(
        authorize_socket_project_chat_resume.__globals__, "_authenticate_socket_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_resume.__globals__, "is_subscription_authorized", lambda *args: True
    )
    service.chat.get_session_by_filterable.return_value = (session, Mock())
    service.chat.get_history_by_id_like.return_value = message
    request = create_request("Bearer access-token")

    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)

    message.message.graph_interrupt = {"type": "approval_request", "thread_id": "thread-1"}
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)

    message.message.graph_interrupt = {"thread_id": "thread-1"}
    response = authorize_socket_project_chat_resume(request, "project", session.get_uid(), form, service)
    assert orjson.loads(response.body) == {}


def test_socket_chat_resume_http_route_requires_bearer_and_valid_body(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = create_authorization_service()
    session = ChatSession.model_construct(id=SnowflakeID(3), user_id=user.id)
    message = ChatHistory.model_construct(
        id=SnowflakeID(4),
        chat_session_id=session.id,
        is_received=True,
        message=ChatContentModel(content="", graph_interrupt={"thread_id": "thread-1"}),
    )
    service.chat.get_session_by_filterable.return_value = (session, Mock())
    service.chat.get_history_by_id_like.return_value = message
    monkeypatch.setattr(
        authorize_socket_project_chat_resume.__globals__["AuthSecurity"],
        "decode_access_token",
        lambda token: {"sub": str(user.id)},
    )
    monkeypatch.setattr(
        authorize_socket_project_chat_resume.__globals__["Auth"], "get_user_by_id", lambda user_id: user
    )
    monkeypatch.setitem(
        authorize_socket_project_chat_resume.__globals__, "is_subscription_authorized", lambda *args: True
    )

    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is authorize_socket_project_chat_resume
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service
    client = TestClient(app)
    path = f"/auth/socket/board/project/chat/session/{session.get_uid()}/resume"
    body = {"message_uid": message.get_uid(), "thread_id": "thread-1"}

    assert client.post(path, json=body).status_code == 401
    response = client.post(path, json=body, headers={"Authorization": "Bearer access-token"})
    assert response.status_code == 200
    assert response.json() == {}
    assert (
        client.post(
            path, json={**body, "thread_id": "other"}, headers={"Authorization": "Bearer access-token"}
        ).status_code
        == 403
    )
    assert (
        client.post(path, json={**body, "thread_id": ""}, headers={"Authorization": "Bearer access-token"}).status_code
        == 400
    )


def test_pending_chat_resume_checks_approval_detail_and_terminal_state() -> None:
    repository = Mock(spec=Repository)
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    session = ChatSession.model_construct(id=SnowflakeID(3))
    history = ChatHistory.model_construct(id=SnowflakeID(4))
    approval = GraphApprovalRequest.model_construct(
        id=SnowflakeID(5),
        request_type=GraphApprovalOriginType.Chat,
        status=GraphApprovalStatus.Pending,
        thread_id="thread-1",
        expires_at=None,
    )
    detail = ChatGraphApprovalRequest.model_construct(chat_session_id=session.id, chat_history_id=history.id)
    repository.graph_approval_request.get_by_id_like.return_value = approval
    repository.graph_approval_request.get_detail.return_value = detail

    assert service.is_pending_chat_resume(approval.id, session, history, "thread-1")
    repository.graph_approval_request.get_by_id_like.assert_called_once_with(approval.id)

    approval.status = GraphApprovalStatus.Resolved
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")

    approval.status = GraphApprovalStatus.Pending
    assert not service.is_pending_chat_resume(approval.id, session, history, "other-thread")
    detail.chat_history_id = SnowflakeID(8)
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")
    detail.chat_history_id = history.id
    detail.chat_session_id = SnowflakeID(8)
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")
    detail.chat_session_id = session.id
    approval.expires_at = SafeDateTime.now()
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")
    approval.expires_at = None
    approval.request_type = GraphApprovalOriginType.Editor
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")
    repository.graph_approval_request.get_by_id_like.return_value = None
    assert not service.is_pending_chat_resume(approval.id, session, history, "thread-1")


def test_editor_approval_response_marks_durable_resume_transport() -> None:
    repository = Mock(spec=Repository)
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    approval = Mock(spec=GraphApprovalRequest)
    approval.id = SnowflakeID(5)
    approval.request_type = GraphApprovalOriginType.Editor
    approval.api_response.return_value = {"uid": approval.id.to_short_code()}
    repository.graph_approval_request.get_detail.return_value = None

    repository.internal_bot_run.get_editor_run_by_approval.return_value = None
    response = service.get_api_response(approval)
    assert response["durable_run"] is False
    assert response["durable_run_status"] is None
    assert response["durable_run_task_id"] is None
    assert response["durable_run_kind"] is None

    run = Mock()
    run.client_task_id = "task-id"
    run.kind = InternalBotRunKind.EditorChat
    repository.internal_bot_run.get_editor_run_by_approval.return_value = run
    for status in (
        InternalBotRunStatus.AwaitingApproval,
        InternalBotRunStatus.Resuming,
        InternalBotRunStatus.Uncertain,
    ):
        run.status = status
        response = service.get_api_response(approval)
        assert response["durable_run"] is True
        assert response["durable_run_status"] == status.value
        assert response["durable_run_task_id"] == "task-id"
        assert response["durable_run_kind"] == InternalBotRunKind.EditorChat.value
    repository.internal_bot_run.get_editor_run_by_approval.assert_called_with(approval.id)


def test_board_chat_approval_response_marks_durable_resume_transport() -> None:
    repository = Mock(spec=Repository)
    service = GraphApprovalRequestService(lambda service_type: None, lambda name: None, repository)
    approval = Mock(spec=GraphApprovalRequest)
    approval.id = SnowflakeID(6)
    approval.request_type = GraphApprovalOriginType.Chat
    approval.api_response.return_value = {"uid": approval.id.to_short_code()}
    repository.graph_approval_request.get_detail.return_value = None

    repository.internal_bot_run.get_board_chat_run_by_approval.return_value = None
    response = service.get_api_response(approval)
    assert response["durable_run"] is False
    assert response["durable_run_status"] is None

    run = Mock()
    repository.internal_bot_run.get_board_chat_run_by_approval.return_value = run
    for status in (
        InternalBotRunStatus.AwaitingApproval,
        InternalBotRunStatus.Resuming,
        InternalBotRunStatus.Uncertain,
    ):
        run.status = status
        response = service.get_api_response(approval)
        assert response["durable_run"] is True
        assert response["durable_run_status"] == status.value
    repository.internal_bot_run.get_board_chat_run_by_approval.assert_called_with(approval.id)


@pytest.mark.parametrize(
    ("document_name", "expected"),
    [
        ("card:card-id:description", (SocketTopic.BoardCard, "card-id")),
        ("board-column-name:project-id:column-id", (SocketTopic.Board, "project-id")),
        ("board-settings:project-id", (SocketTopic.BoardSettings, "project-id")),
        ("bot-schedule:project-id:schedule-id", (SocketTopic.BoardSettings, "project-id")),
        ("wiki:wiki-id:content", (SocketTopic.BoardWikiPrivate, "wiki-id")),
        ("app-settings:bot-id:bot-value", (SocketTopic.AppSettings, SettingSocketTopicID.Bot.value)),
        ("app-settings:bot-id:internal-bot-value", (SocketTopic.AppSettings, SettingSocketTopicID.InternalBot.value)),
        ("app-settings:key-id:api-key", (SocketTopic.AppSettings, SettingSocketTopicID.ApiKey.value)),
        ("app-settings:group-id:mcp-tool-group", (SocketTopic.AppSettings, SettingSocketTopicID.McpToolGroup.value)),
        (
            "app-settings:rule-id:notification-schedule-rule",
            (SocketTopic.AppSettings, SettingSocketTopicID.NotificationSchedule.value),
        ),
    ],
)
def test_editor_document_subscription_matches_node_document_scope(
    document_name: str, expected: tuple[SocketTopic, str]
) -> None:
    assert _editor_document_subscription(document_name) == expected


@pytest.mark.parametrize(
    "document_name",
    [
        "",
        "card",
        "card:",
        "card::description",
        "card:one:two:three",
        "unknown:one",
        "app-settings:one",
        "app-settings:one:unknown",
    ],
)
def test_editor_document_subscription_rejects_invalid_names(document_name: str) -> None:
    assert _editor_document_subscription(document_name) is None


def test_editor_document_authorization_uses_current_user_and_topic_permission(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = DomainService()
    form = SocketEditorDocumentAuthorizationForm(document_name="card:card-id:description")
    checked: list[tuple[User, SocketTopic, str]] = []
    monkeypatch.setitem(authorize_socket_editor_document.__globals__, "_authenticate_socket_user", lambda request: user)

    def check_permission(_service: DomainService, current_user: User, topic: SocketTopic, topic_id: str) -> bool:
        checked.append((current_user, topic, topic_id))
        return False

    monkeypatch.setattr(SocketAuthorization, "is_subscription_authorized", check_permission)

    response = authorize_socket_editor_document(create_request("Bearer access-token"), form, service)

    assert orjson.loads(response.body) == {"authorized": False, "writable": False, "user_name": None}
    assert checked == [(user, SocketTopic.BoardCard, "card-id")]

    monkeypatch.setattr(SocketAuthorization, "is_subscription_authorized", lambda *_args: True)
    monkeypatch.setitem(
        authorize_socket_editor_document.__globals__,
        "is_editor_document_write_authorized",
        lambda *_args: True,
    )
    response = authorize_socket_editor_document(create_request("Bearer access-token"), form, service)
    assert orjson.loads(response.body) == {"authorized": True, "writable": True, "user_name": "Test User"}


def test_editor_document_write_authorization_tracks_current_card_role() -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    card = Card.model_construct(id=SnowflakeID(3), project_id=project.id)
    service = create_authorization_service()
    service.card.get_by_id_like.return_value = card
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (True, object())
    subscription = (SocketTopic.BoardCard, card.get_uid())

    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Read.value]
    assert not _is_editor_document_write_authorized(service, user, subscription)

    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.CardUpdate.value]
    assert _is_editor_document_write_authorized(service, user, subscription)


def test_editor_document_write_authorization_uses_existing_settings_roles() -> None:
    admin = create_user(is_admin=True)
    service = create_authorization_service()

    service.api_key.get_role.return_value = ApiKeyRole.model_construct(actions=[ApiKeyRoleAction.Read.value])
    api_key_subscription = (SocketTopic.AppSettings, SettingSocketTopicID.ApiKey.value)
    assert not _is_editor_document_write_authorized(service, admin, api_key_subscription)
    service.api_key.get_role.return_value = ApiKeyRole.model_construct(actions=[ApiKeyRoleAction.Update.value])
    assert _is_editor_document_write_authorized(service, admin, api_key_subscription)

    service.mcp_tool_group.get_role.return_value = McpRole.model_construct(actions=[McpRoleAction.Read.value])
    mcp_subscription = (SocketTopic.AppSettings, SettingSocketTopicID.McpToolGroup.value)
    assert not _is_editor_document_write_authorized(service, admin, mcp_subscription)
    service.mcp_tool_group.get_role.return_value = McpRole.model_construct(actions=[McpRoleAction.Update.value])
    assert _is_editor_document_write_authorized(service, admin, mcp_subscription)

    service.user.get_setting_role.return_value = SettingRole.model_construct(actions=[SettingRoleAction.BotRead.value])
    bot_subscription = (SocketTopic.AppSettings, SettingSocketTopicID.Bot.value)
    assert not _is_editor_document_write_authorized(service, admin, bot_subscription)
    service.user.get_setting_role.return_value = SettingRole.model_construct(
        actions=[SettingRoleAction.BotUpdate.value]
    )
    assert _is_editor_document_write_authorized(service, admin, bot_subscription)


def test_editor_document_authorization_requires_user_authentication() -> None:
    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_editor_document(
            create_request(None),
            SocketEditorDocumentAuthorizationForm(document_name="card:card-id"),
            DomainService(),
        )


@pytest.mark.parametrize(
    ("topic", "scope_service", "document_type"),
    [
        (SocketTopic.BoardCard, "card", "card"),
        (SocketTopic.BoardWikiPrivate, "project_wiki", "wiki"),
    ],
)
def test_editor_ai_authorization_binds_document_and_project(
    monkeypatch: MonkeyPatch, topic: SocketTopic, scope_service: str, document_type: str
) -> None:
    user = create_user()
    service = create_authorization_service()
    project_uid = SnowflakeID(2).to_short_code()
    scope_uid = SnowflakeID(3).to_short_code()
    form = SocketEditorAiAuthorizationForm(
        project_uid=project_uid, scope_uid=scope_uid, document_name=f"{document_type}:{scope_uid}:description"
    )
    project = Mock(id=SnowflakeID(2))
    scope = Mock(project_id=project.id)
    service.project.get_by_id_like.return_value = project
    getattr(service, scope_service).get_by_id_like.return_value = scope
    monkeypatch.setitem(authorize_socket_editor_ai.__globals__, "_authenticate_socket_user", lambda request: user)
    monkeypatch.setattr(
        SocketAuthorization,
        "is_subscription_authorized",
        lambda current_service, current_user, current_topic, topic_id: current_service is service
        and current_user is user
        and current_topic == topic
        and topic_id == scope_uid,
    )

    response = authorize_socket_editor_ai(create_request("Bearer access-token"), form, service)

    assert orjson.loads(response.body) == {}
    service.project.get_by_id_like.assert_called_once_with(project.id)
    getattr(service, scope_service).get_by_id_like.assert_called_once_with(SnowflakeID(3))

    scope.project_id = SnowflakeID(4)
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_editor_ai(create_request("Bearer access-token"), form, service)

    scope.project_id = project.id
    monkeypatch.setattr(SocketAuthorization, "is_subscription_authorized", lambda *args: False)
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_editor_ai(create_request("Bearer access-token"), form, service)


def test_editor_ai_authorization_rejects_mismatched_or_unapproved_scope(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    service = create_authorization_service()
    project_uid = SnowflakeID(2).to_short_code()
    scope_uid = SnowflakeID(3).to_short_code()
    form = SocketEditorAiAuthorizationForm(
        project_uid=project_uid, scope_uid=scope_uid, document_name=f"card:{scope_uid}:description"
    )
    service.project.get_by_id_like.return_value = Mock(id=SnowflakeID(2))
    monkeypatch.setitem(authorize_socket_editor_ai.__globals__, "_authenticate_socket_user", lambda request: user)

    for subscription in (None, (SocketTopic.BoardCard, SnowflakeID(4).to_short_code()), (SocketTopic.Board, scope_uid)):
        monkeypatch.setitem(
            authorize_socket_editor_ai.__globals__,
            "authorized_editor_document_subscription",
            lambda current_service, current_user, document_name: subscription,
        )
        with pytest.raises(ApiException.Forbidden_403):
            authorize_socket_editor_ai(create_request("Bearer access-token"), form, service)

    service.project.get_by_id_like.return_value = None
    with pytest.raises(ApiException.Forbidden_403):
        authorize_socket_editor_ai(create_request("Bearer access-token"), form, service)


def test_editor_ai_authorization_requires_bearer_token() -> None:
    form = SocketEditorAiAuthorizationForm(
        project_uid=SnowflakeID(2).to_short_code(),
        scope_uid=SnowflakeID(3).to_short_code(),
        document_name="card:scope:description",
    )
    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_editor_ai(create_request(None), form, create_authorization_service())


def test_editor_http_document_authorization_accepts_existing_internal_user_token(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    monkeypatch.setattr(
        authorize_socket_editor_http_document.__globals__["Auth"], "validate_user_by_api_token", lambda headers: user
    )
    monkeypatch.setattr(
        SocketAuthorization, "is_subscription_authorized", lambda service, current_user, topic, topic_id: True
    )

    request = Request({"type": "http", "headers": [(b"x-api-token", b"internal-token")]})

    response = authorize_socket_editor_http_document(
        request,
        SocketEditorDocumentAuthorizationForm(document_name="card:card-id"),
        create_authorization_service(),
    )

    assert orjson.loads(response.body) == {"authorized": True}


def test_editor_http_document_authorization_uses_cookie_validated_user(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    monkeypatch.setattr(authorize_socket_editor_http_document.__globals__["Auth"], "validate", lambda headers: user)
    monkeypatch.setattr(
        SocketAuthorization, "is_subscription_authorized", lambda service, current_user, topic, topic_id: True
    )

    response = authorize_socket_editor_http_document(
        create_request("Bearer access-token"),
        SocketEditorDocumentAuthorizationForm(document_name="card:card-id"),
        create_authorization_service(),
    )

    assert orjson.loads(response.body) == {"authorized": True}


def test_editor_http_document_authorization_requires_write_permission_for_mutations(
    monkeypatch: MonkeyPatch,
) -> None:
    user = create_user()
    service = create_authorization_service()
    subscription = (SocketTopic.BoardCard, "card-id")
    monkeypatch.setitem(
        authorize_socket_editor_http_document.__globals__, "_authenticate_editor_http_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_editor_http_document.__globals__,
        "authorized_editor_document_subscription",
        lambda current_service, current_user, document_name: subscription,
    )
    monkeypatch.setitem(
        authorize_socket_editor_http_document.__globals__,
        "is_editor_document_write_authorized",
        lambda current_service, current_user, current_subscription: False,
    )

    response = authorize_socket_editor_http_document(
        create_request("Bearer access-token"),
        SocketEditorDocumentAuthorizationForm(document_name="card:card-id", write=True),
        service,
    )

    assert orjson.loads(response.body) == {"authorized": False}

    response = authorize_socket_editor_http_document(
        create_request("Bearer access-token"),
        SocketEditorDocumentAuthorizationForm(document_name="card:card-id", write=False),
        service,
    )
    assert orjson.loads(response.body) == {"authorized": True}


def test_editor_http_document_authorization_rejects_bearer_without_refresh_cookie() -> None:
    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_editor_http_document(
            create_request("Bearer access-token"),
            SocketEditorDocumentAuthorizationForm(document_name="card:card-id"),
            create_authorization_service(),
        )


def test_editor_http_document_authorization_rejects_ineligible_user(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        authorize_socket_editor_http_document.__globals__["Auth"],
        "validate_user_by_api_token",
        lambda headers: create_user(deleted=True),
    )

    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_editor_http_document(
            Request({"type": "http", "headers": [(b"x-api-token", b"internal-token")]}),
            SocketEditorDocumentAuthorizationForm(document_name="card:card-id"),
            create_authorization_service(),
        )


def test_editor_http_documents_authorization_checks_unique_names_for_one_user(monkeypatch: MonkeyPatch) -> None:
    user = create_user()
    checked: list[str] = []
    monkeypatch.setitem(
        authorize_socket_editor_http_documents.__globals__, "_authenticate_editor_http_user", lambda request: user
    )

    def check_permission(service: DomainService, current_user: User, topic: SocketTopic, topic_id: str) -> bool:
        assert current_user is user
        assert topic == SocketTopic.BoardCard
        checked.append(topic_id)
        return topic_id != "denied"

    monkeypatch.setattr(SocketAuthorization, "is_subscription_authorized", check_permission)

    response = authorize_socket_editor_http_documents(
        create_request("Bearer access-token"),
        SocketEditorDocumentsAuthorizationForm(document_names=["card:allowed", "card:allowed", "card:denied"]),
        DomainService(),
    )

    assert orjson.loads(response.body) == {"authorized": False}
    assert checked == ["allowed", "denied"]


def test_editor_http_documents_authorization_applies_write_permission_to_each_document(
    monkeypatch: MonkeyPatch,
) -> None:
    user = create_user()
    checked: list[str] = []
    monkeypatch.setitem(
        authorize_socket_editor_http_documents.__globals__, "_authenticate_editor_http_user", lambda request: user
    )
    monkeypatch.setitem(
        authorize_socket_editor_http_documents.__globals__,
        "authorized_editor_document_subscription",
        lambda service, current_user, name: (SocketTopic.BoardCard, name),
    )

    def check_write(
        service: DomainService,
        current_user: User,
        subscription: tuple[SocketTopic, str],
    ) -> bool:
        checked.append(subscription[1])
        return subscription[1] != "card:denied"

    monkeypatch.setitem(
        authorize_socket_editor_http_documents.__globals__,
        "is_editor_document_write_authorized",
        check_write,
    )

    response = authorize_socket_editor_http_documents(
        create_request("Bearer access-token"),
        SocketEditorDocumentsAuthorizationForm(document_names=["card:allowed", "card:denied"], write=True),
        DomainService(),
    )

    assert orjson.loads(response.body) == {"authorized": False}
    assert checked == ["card:allowed", "card:denied"]


def test_editor_http_documents_authorization_rejects_invalid_scope(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setitem(
        authorize_socket_editor_http_documents.__globals__,
        "_authenticate_editor_http_user",
        lambda request: create_user(),
    )
    response = authorize_socket_editor_http_documents(
        create_request("Bearer access-token"),
        SocketEditorDocumentsAuthorizationForm(document_names=["unknown:document"]),
        DomainService(),
    )
    assert orjson.loads(response.body) == {"authorized": False}


def test_editor_http_documents_authorization_authenticates_empty_list() -> None:
    with pytest.raises(ApiException.Unauthorized_401):
        authorize_socket_editor_http_documents(
            create_request(None),
            SocketEditorDocumentsAuthorizationForm(document_names=[]),
            DomainService(),
        )


@pytest.mark.parametrize("document_names", [[""], ["x" * 513], ["card:ok"] * 257])
def test_editor_http_documents_authorization_bounds_payload(document_names: list[str]) -> None:
    with pytest.raises(ValidationError):
        SocketEditorDocumentsAuthorizationForm(document_names=document_names)


@pytest.mark.parametrize("topic", [SocketTopic.Board, SocketTopic.BoardWiki, SocketTopic.Dashboard])
def test_project_topics_require_current_membership(topic: SocketTopic) -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    service = create_authorization_service()
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (True, object())

    assert _is_subscription_authorized(service, user, topic, project.get_uid())

    service.project.is_assigned.return_value = (False, None)
    assert not _is_subscription_authorized(service, user, topic, project.get_uid())


def test_board_settings_requires_update_role_for_non_admin() -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    service = create_authorization_service()
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (True, object())
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Read.value]

    assert not _is_subscription_authorized(service, user, SocketTopic.BoardSettings, project.get_uid())

    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Update.value]
    assert _is_subscription_authorized(service, user, SocketTopic.BoardSettings, project.get_uid())


def test_board_card_allows_project_member_or_card_update_role() -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    card = Card.model_construct(id=SnowflakeID(3), project_id=project.id)
    service = create_authorization_service()
    service.card.get_by_id_like.return_value = card
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (True, object())
    service.project.get_user_role_actions_by_project.return_value = []

    assert _is_subscription_authorized(service, user, SocketTopic.BoardCard, card.get_uid())

    service.project.is_assigned.return_value = (False, None)
    assert not _is_subscription_authorized(service, user, SocketTopic.BoardCard, card.get_uid())

    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.CardUpdate.value]
    assert _is_subscription_authorized(service, user, SocketTopic.BoardCard, card.get_uid())


def test_private_wiki_allows_assignment_or_project_update_role() -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    wiki = ProjectWiki.model_construct(id=SnowflakeID(3), project_id=project.id, is_public=False)
    service = create_authorization_service()
    service.project_wiki.get_by_id_like.return_value = wiki
    service.project_wiki.is_assigned.return_value = True
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (True, None)

    assert _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())

    service.project_wiki.is_assigned.return_value = False
    service.project.get_by_id_like.return_value = project
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Update.value]
    assert _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())

    service.project.get_user_role_actions_by_project.return_value = []
    assert not _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())


@pytest.mark.parametrize("is_public", [True, False])
def test_wiki_rejects_nonmember_even_with_wiki_access_or_stale_role(is_public: bool) -> None:
    user = create_user()
    project = Project.model_construct(id=SnowflakeID(2))
    wiki = ProjectWiki.model_construct(id=SnowflakeID(3), project_id=project.id, is_public=is_public)
    service = create_authorization_service()
    service.project_wiki.get_by_id_like.return_value = wiki
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (False, None)
    service.project_wiki.is_assigned.return_value = True
    service.project.get_user_role_actions_by_project.return_value = [ProjectRoleAction.Update.value]

    assert not _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())
    service.project_wiki.is_assigned.assert_not_called()


def test_wiki_admin_access_requires_existing_project() -> None:
    user = create_user(is_admin=True)
    project = Project.model_construct(id=SnowflakeID(2))
    wiki = ProjectWiki.model_construct(id=SnowflakeID(3), project_id=project.id, is_public=False)
    service = create_authorization_service()
    service.project_wiki.get_by_id_like.return_value = wiki
    service.project.get_by_id_like.return_value = project
    service.project.is_assigned.return_value = (False, None)

    assert _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())
    service.project.get_by_id_like.return_value = None
    assert not _is_subscription_authorized(service, user, SocketTopic.BoardWikiPrivate, wiki.get_uid())


def test_user_topic_rejects_self_and_requires_admin_or_related_user() -> None:
    user = create_user()
    target = create_user(user_id=2)
    service = create_authorization_service()
    service.user.get_by_id_like.return_value = target
    service.project.are_users_related.return_value = False

    assert not _is_subscription_authorized(service, user, SocketTopic.User, target.get_uid())

    service.project.are_users_related.return_value = True
    assert _is_subscription_authorized(service, user, SocketTopic.User, target.get_uid())

    service.user.get_by_id_like.return_value = user
    assert not _is_subscription_authorized(service, user, SocketTopic.User, user.get_uid())


def test_app_settings_preserves_existing_role_categories() -> None:
    user = create_user(is_admin=True)
    service = create_authorization_service()
    service.api_key.get_role.return_value = ApiKeyRole.model_construct(actions=["read"])
    service.mcp_tool_group.get_role.return_value = McpRole.model_construct(actions=["read"])
    service.user.get_setting_role.return_value = SettingRole.model_construct(actions=["bot_read"])
    assert _is_subscription_authorized(service, user, SocketTopic.AppSettings, SettingSocketTopicID.ApiKey.value)
    assert _is_subscription_authorized(service, user, SocketTopic.AppSettings, SettingSocketTopicID.McpToolGroup.value)
    assert _is_subscription_authorized(service, user, SocketTopic.AppSettings, SettingSocketTopicID.Bot.value)
    assert not _is_subscription_authorized(
        service,
        create_user(is_admin=False),
        SocketTopic.AppSettings,
        SettingSocketTopicID.Bot.value,
    )


def test_fixed_scope_topics_reject_forged_topic_ids() -> None:
    user = create_user(is_admin=True)
    service = create_authorization_service()
    service.user.get_setting_role.return_value = SettingRole.model_construct(
        actions=[SettingRoleAction.OllamaRead.value]
    )

    assert _is_subscription_authorized(service, user, SocketTopic.Global, "all")
    assert not _is_subscription_authorized(service, user, SocketTopic.Global, "forged")
    assert _is_subscription_authorized(service, user, SocketTopic.UserPrivate, user.get_uid())
    assert not _is_subscription_authorized(service, user, SocketTopic.UserPrivate, "forged")
    assert _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "all")
    assert not _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "forged")


def test_ollama_subscription_requires_the_current_setting_role() -> None:
    user = create_user(is_admin=True)
    service = create_authorization_service()

    service.user.get_setting_role.return_value = None
    assert not _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "all")

    service.user.get_setting_role.return_value = SettingRole.model_construct(actions=[SettingRoleAction.BotRead.value])
    assert not _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "all")

    service.user.get_setting_role.return_value = SettingRole.model_construct(
        actions=[SettingRoleAction.OllamaRead.value]
    )
    assert _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "all")

    service.user.get_setting_role.return_value = SettingRole.model_construct(actions=["*"])
    assert _is_subscription_authorized(service, user, SocketTopic.OllamaManager, "all")
    assert not _is_subscription_authorized(service, create_user(), SocketTopic.OllamaManager, "all")


def test_ollama_subscription_preserves_the_full_admin_exception() -> None:
    previous_emails = Env.FULL_ADMIN_ACCESS_EMAILS
    Env.update_env("FULL_ADMIN_ACCESS_EMAILS", "full-admin@example.com")
    try:
        service = create_authorization_service()
        service.user.get_setting_role.return_value = None

        assert _is_subscription_authorized(
            service, create_user(email="full-admin@example.com", is_admin=True), SocketTopic.OllamaManager, "all"
        )
        assert not _is_subscription_authorized(
            service, create_user(email="full-admin@example.com"), SocketTopic.OllamaManager, "all"
        )
        assert not _is_subscription_authorized(service, create_user(is_admin=True), SocketTopic.OllamaManager, "all")
    finally:
        Env.update_env("FULL_ADMIN_ACCESS_EMAILS", ",".join(previous_emails))
