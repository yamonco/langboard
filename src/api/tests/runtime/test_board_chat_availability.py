from datetime import timezone
from unittest.mock import Mock
import orjson
import pytest
import requests
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.auth import SocketAuthApi
from langboard.routes.auth.SocketAuthApi import (
    _authenticate_socket_user,
    get_socket_project_chat_availability,
)
from langboard_shared.core.routing import ApiException, AppRouter, SocketTopic
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import InternalBot, User
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from pytest import MonkeyPatch


def create_bot(
    platform: BotPlatform = BotPlatform.Default,
    running_type: BotPlatformRunningType = BotPlatformRunningType.Default,
) -> InternalBot:
    return InternalBot.model_construct(
        bot_type=InternalBotType.ProjectChat,
        display_name="Project Assistant",
        platform=platform,
        platform_running_type=running_type,
        api_url="https://bot.example.invalid/",
        api_key="private-test-key",
        created_at=SafeDateTime(2026, 7, 27, 11, 1, 0, 366890, tzinfo=timezone.utc),
        updated_at=SafeDateTime(2026, 9, 3, 13, 24, 5, 461275, tzinfo=timezone.utc),
    )


def create_request() -> Request:
    return Request({"type": "http", "headers": [(b"authorization", b"Bearer access-token")]})


@pytest.fixture(autouse=True)
def authorize_board(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(SocketAuthApi, "_authenticate_socket_user", lambda request: Mock())
    monkeypatch.setattr(
        SocketAuthApi,
        "is_subscription_authorized",
        lambda service, user, topic, topic_id: topic == SocketTopic.Board and topic_id == "project-uid",
    )


def test_chat_availability_rejects_nonmember_without_querying_bot(monkeypatch: MonkeyPatch) -> None:
    service = Mock()
    monkeypatch.setattr(SocketAuthApi, "is_subscription_authorized", lambda *args: False)

    with pytest.raises(ApiException.Forbidden_403):
        get_socket_project_chat_availability(create_request(), "project-uid", service)

    service.project.get_assigned_internal_bot_by_type.assert_not_called()


def test_chat_availability_requires_socket_auth_before_querying_bot(monkeypatch: MonkeyPatch) -> None:
    service = Mock()
    probe = Mock()
    monkeypatch.setattr(SocketAuthApi, "_authenticate_socket_user", Mock(side_effect=ApiException.Unauthorized_401()))
    monkeypatch.setattr(SocketAuthApi.requests, "get", probe)

    with pytest.raises(ApiException.Unauthorized_401):
        get_socket_project_chat_availability(create_request(), "project-uid", service)

    service.project.get_assigned_internal_bot_by_type.assert_not_called()
    probe.assert_not_called()


def test_chat_availability_accepts_socket_bearer_without_cookie(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(id=SnowflakeID(1), activated_at=SafeDateTime.now(), deleted_at=None)
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = None
    monkeypatch.setattr(SocketAuthApi, "_authenticate_socket_user", _authenticate_socket_user)
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "decode_access_token", lambda token: {"sub": "1"})
    monkeypatch.setattr(SocketAuthApi.Auth, "get_user_by_id", lambda user_id: user)

    response = get_socket_project_chat_availability(create_request(), "project-uid", service)

    assert orjson.loads(response.body) == {"available": False, "bot": None}


def test_chat_availability_http_route_accepts_bearer_without_cookie(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(id=SnowflakeID(1), activated_at=SafeDateTime.now(), deleted_at=None)
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = None
    monkeypatch.setattr(SocketAuthApi, "_authenticate_socket_user", _authenticate_socket_user)
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "decode_access_token", lambda token: {"sub": "1"})
    monkeypatch.setattr(SocketAuthApi.Auth, "get_user_by_id", lambda user_id: user)

    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    route = next(
        route
        for route in AppRouter.api.routes
        if isinstance(route, APIRoute) and route.endpoint is get_socket_project_chat_availability
    )
    dependency = next(item.call for item in route.dependant.dependencies if item.name == "service")
    assert dependency is not None
    app.dependency_overrides[dependency] = lambda: service

    client = TestClient(app)
    path = "/auth/socket/board/project-uid/chat/availability"
    assert client.get(path).status_code == 401
    response = client.get(path, headers={"Authorization": "Bearer access-token"})

    assert response.status_code == 200
    assert response.json() == {"available": False, "bot": None}


def test_chat_availability_without_assigned_bot_does_not_probe_health(monkeypatch: MonkeyPatch) -> None:
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = None
    probe = Mock()
    monkeypatch.setattr(SocketAuthApi.requests, "get", probe)

    response = get_socket_project_chat_availability(create_request(), "project-uid", service)

    assert orjson.loads(response.body) == {"available": False, "bot": None}
    service.project.get_assigned_internal_bot_by_type.assert_called_once_with(
        "project-uid", InternalBotType.ProjectChat
    )
    probe.assert_not_called()


@pytest.mark.parametrize(
    ("platform", "running_type", "expected_url", "expected_key"),
    [
        (BotPlatform.Default, BotPlatformRunningType.Default, None, None),
        (
            BotPlatform.Langflow,
            BotPlatformRunningType.Endpoint,
            "https://bot.example.invalid/health",
            "private-test-key",
        ),
    ],
)
def test_chat_availability_checks_supported_bot_health(
    monkeypatch: MonkeyPatch,
    platform: BotPlatform,
    running_type: BotPlatformRunningType,
    expected_url: str | None,
    expected_key: str | None,
) -> None:
    bot = create_bot(platform, running_type)
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = (bot, Mock())
    probe = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(SocketAuthApi.requests, "get", probe)

    response = get_socket_project_chat_availability(create_request(), "project-uid", service)
    payload = orjson.loads(response.body)

    assert payload["available"] is True
    assert payload["bot"]["bot_type"] == InternalBotType.ProjectChat.value
    assert payload["bot"]["display_name"] == "Project Assistant"
    assert payload["bot"]["created_at"] == "2026-07-27T11:01:00.366Z"
    assert payload["bot"]["updated_at"] == "2026-09-03T13:24:05.461Z"
    assert "api_key" not in payload["bot"]
    assert "api_url" not in payload["bot"]
    assert probe.call_args.args == (expected_url or f"{SocketAuthApi.Env.DEFAULT_GRAPH_URL.rstrip('/')}/health",)
    assert probe.call_args.kwargs["headers"].get("X-API-KEY") == expected_key
    assert probe.call_args.kwargs["timeout"] == SocketAuthApi.Env.AI_REQUEST_TIMEOUT


@pytest.mark.parametrize(
    ("platform", "running_type"),
    [
        (BotPlatform.N8N, BotPlatformRunningType.Default),
        (BotPlatform.Langflow, BotPlatformRunningType.Default),
    ],
)
def test_chat_availability_rejects_unsupported_bot_runtime(
    monkeypatch: MonkeyPatch, platform: BotPlatform, running_type: BotPlatformRunningType
) -> None:
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = (create_bot(platform, running_type), Mock())
    probe = Mock()
    monkeypatch.setattr(SocketAuthApi.requests, "get", probe)

    response = get_socket_project_chat_availability(create_request(), "project-uid", service)

    assert orjson.loads(response.body)["available"] is False
    probe.assert_not_called()


@pytest.mark.parametrize("failure", ["status", "network"])
def test_chat_availability_health_failure_returns_unavailable(monkeypatch: MonkeyPatch, failure: str) -> None:
    service = Mock()
    service.project.get_assigned_internal_bot_by_type.return_value = (create_bot(), Mock())
    if failure == "network":
        probe = Mock(side_effect=requests.ConnectionError("unavailable"))
    else:
        probe = Mock(return_value=Mock(status_code=503))
    monkeypatch.setattr(SocketAuthApi.requests, "get", probe)

    response = get_socket_project_chat_availability(create_request(), "project-uid", service)

    assert orjson.loads(response.body)["available"] is False
    assert orjson.loads(response.body)["bot"]["display_name"] == "Project Assistant"
