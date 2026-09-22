from unittest.mock import Mock
import orjson
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares import ApiAuthMiddleware
from langboard.routes.notification.NotificationApi import (
    delete_all_notifications,
    delete_notification,
    read_all_notifications,
    read_notification,
)
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import User, UserNotification
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.NotificationService import NotificationService
from langboard_shared.helpers import InfraHelper, MiddlewareHelper
from langboard_shared.infrastructure.repositories import Repository
from langboard_shared.publishers.UserPublisher import UserPublisher
from pytest import MonkeyPatch


def _user(user_id: int) -> User:
    return User.model_construct(id=SnowflakeID(user_id))


@pytest.mark.parametrize(
    ("handler", "method"),
    [(read_notification, "read"), (delete_notification, "delete")],
)
def test_notification_command_uses_current_user(monkeypatch: MonkeyPatch, handler, method: str) -> None:
    user = _user(1)
    notification = Mock()
    mutation = {"action": method, "notification_uid": SnowflakeID(2).to_short_code(), "unread_count": 0}
    getattr(notification, method).return_value = mutation
    monkeypatch.setattr(DomainService, "notification", notification)
    service = DomainService()
    uid = SnowflakeID(2).to_short_code()

    response = handler(uid, user, service)

    assert response.status_code == 200
    assert orjson.loads(response.body) == mutation
    getattr(notification, method).assert_called_once_with(user, SnowflakeID(2))


@pytest.mark.parametrize(
    ("handler", "method"),
    [(read_all_notifications, "read_all"), (delete_all_notifications, "delete_all")],
)
def test_bulk_notification_command_uses_current_user(monkeypatch: MonkeyPatch, handler, method: str) -> None:
    user = _user(1)
    notification = Mock()
    mutation = {"action": method, "unread_count": 0}
    getattr(notification, method).return_value = mutation
    monkeypatch.setattr(DomainService, "notification", notification)
    service = DomainService()

    response = handler(user, service)

    assert response.status_code == 200
    assert orjson.loads(response.body) == mutation
    getattr(notification, method).assert_called_once_with(user)


@pytest.mark.parametrize("handler", [read_notification, delete_notification])
@pytest.mark.parametrize("uid", ["invalid", "!!!!!!!!!!!", ""])
def test_notification_command_rejects_invalid_uid(monkeypatch: MonkeyPatch, handler, uid: str) -> None:
    notification = Mock()
    monkeypatch.setattr(DomainService, "notification", notification)
    service = DomainService()

    with pytest.raises(ApiException.BadRequest_400):
        handler(uid, _user(1), service)

    notification.read.assert_not_called()
    notification.delete.assert_not_called()


@pytest.mark.parametrize(
    "handler", [read_notification, read_all_notifications, delete_notification, delete_all_notifications]
)
def test_notification_commands_require_user_authentication(handler) -> None:
    assert AuthFilter.get_filtered(handler) == "user"


def test_notification_http_routes_use_authentication_middleware(monkeypatch: MonkeyPatch) -> None:
    user = _user(1)
    notification = Mock()
    monkeypatch.setattr(DomainService, "notification", notification)

    def authenticate(scope):
        if scope["headers"] and any(name == b"authorization" for name, _value in scope["headers"]):
            scope["auth"] = user
            return user
        return 401

    monkeypatch.setattr(MiddlewareHelper, "validate_auth", authenticate)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    client = TestClient(app)
    uid = SnowflakeID(2).to_short_code()

    assert client.put(f"/notifications/{uid}/read").status_code == 401
    assert client.delete("/notifications").status_code == 401
    notification.read.assert_not_called()
    notification.delete_all.assert_not_called()

    headers = {"Authorization": "Bearer access-token"}
    assert client.put(f"/notifications/{uid}/read", headers=headers).status_code == 200
    assert client.delete("/notifications", headers=headers).status_code == 200
    notification.read.assert_called_once_with(user, SnowflakeID(2))
    notification.delete_all.assert_called_once_with(user)


@pytest.mark.parametrize("method", ["read", "delete"])
def test_notification_service_rejects_other_users_records(monkeypatch: MonkeyPatch, method: str) -> None:
    notification = UserNotification.model_construct(id=SnowflakeID(2), receiver_id=SnowflakeID(3))
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: notification)
    notification_repo = Mock()
    monkeypatch.setattr(Repository, "user_notification", notification_repo)
    repository = Repository()
    service = NotificationService(lambda service_type: None, lambda name: None, repository)

    publish = Mock()
    monkeypatch.setattr(UserPublisher, "notification_mutated", publish)

    assert getattr(service, method)(_user(1), notification.id) is None

    notification_repo.update.assert_not_called()
    notification_repo.delete.assert_not_called()
    publish.assert_not_called()


@pytest.mark.parametrize("method", ["read", "delete"])
def test_notification_service_changes_owners_records(monkeypatch: MonkeyPatch, method: str) -> None:
    user = _user(1)
    notification = UserNotification.model_construct(id=SnowflakeID(2), receiver_id=user.id, read_at=None)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda model, identifier: notification)
    notification_repo = Mock()
    notification_repo.count_unread.return_value = 3
    monkeypatch.setattr(Repository, "user_notification", notification_repo)
    publish = Mock()
    monkeypatch.setattr(UserPublisher, "notification_mutated", publish)
    repository = Repository()
    service = NotificationService(lambda service_type: None, lambda name: None, repository)

    mutation = getattr(service, method)(user, notification.id)

    assert mutation is not None
    assert mutation["action"] == method
    assert mutation["notification_uid"] == notification.get_uid()
    assert mutation["unread_count"] == 3
    publish.assert_called_once_with(user, mutation)

    if method == "read":
        assert notification.read_at is not None
        assert mutation["read_at"] == notification.read_at.isoformat()
        notification_repo.update.assert_called_once_with(notification)
    else:
        assert "read_at" not in mutation
        notification_repo.delete.assert_called_once_with(notification)


@pytest.mark.parametrize("method", ["read_all", "delete_all"])
def test_bulk_notification_service_publishes_authoritative_state(monkeypatch: MonkeyPatch, method: str) -> None:
    user = _user(1)
    notification_repo = Mock()
    notification_repo.count_unread.return_value = 0
    monkeypatch.setattr(Repository, "user_notification", notification_repo)
    publish = Mock()
    monkeypatch.setattr(UserPublisher, "notification_mutated", publish)
    repository = Repository()
    service = NotificationService(lambda service_type: None, lambda name: None, repository)

    mutation = getattr(service, method)(user)

    assert mutation["action"] == method
    assert mutation["unread_count"] == 0
    publish.assert_called_once_with(user, mutation)
    if method == "read_all":
        read_at = notification_repo.read_all_by_user.call_args.args[1]
        assert mutation["read_at"] == read_at.isoformat()
        notification_repo.read_all_by_user.assert_called_once_with(user, read_at)
    else:
        assert "read_at" not in mutation
        notification_repo.delete_all.assert_called_once_with(user)
