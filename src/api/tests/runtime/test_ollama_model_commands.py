from collections.abc import Iterator
from unittest.mock import Mock
import orjson
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares import ApiAuthMiddleware, RoleMiddleware
from langboard.routes.settings import OllamaApi
from langboard.routes.settings.Form import CopyOllamaModelForm, OllamaModelForm
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import GLOBAL_TOPIC_ID, ApiException, AppRouter, SocketTopic
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import SettingRole, User
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.helpers import MiddlewareHelper
from langboard_shared.security import RoleSecurity
from pytest import MonkeyPatch
from starlette.datastructures import Headers
from starlette.types import Scope


@pytest.fixture
def ollama_url() -> Iterator[str]:
    previous = Env.OLLAMA_API_URL
    url = "http://ollama.example.invalid"
    Env.update_env("OLLAMA_API_URL", url)
    try:
        yield url
    finally:
        Env.update_env("OLLAMA_API_URL", previous)


@pytest.mark.parametrize("handler", [OllamaApi.copy_ollama_model, OllamaApi.delete_ollama_model])
def test_ollama_mutations_require_admin_and_ollama_role(handler: object) -> None:
    assert AuthFilter.get_filtered(handler) == "admin"
    role_model, actions, _finder, allowed_all_admin = RoleFilter.get_filtered(handler)
    assert role_model is SettingRole
    assert actions == [SettingRoleAction.OllamaRead.value]
    assert allowed_all_admin is False


def test_copy_model_publishes_only_after_ollama_success(monkeypatch: MonkeyPatch, ollama_url: str) -> None:
    request = Mock(return_value=Mock(status_code=200))
    publish = Mock()
    monkeypatch.setattr(OllamaApi.requests, "post", request)
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", publish)

    response = OllamaApi.copy_ollama_model(CopyOllamaModelForm(model="source", copy_to="destination"))

    assert request.call_args.args == (f"{ollama_url}/api/copy",)
    assert request.call_args.kwargs["json"] == {"source": "source", "destination": "destination"}
    assert request.call_args.kwargs["timeout"] == Env.AI_REQUEST_TIMEOUT
    assert orjson.loads(response.body) == {"model": "source", "copy_to": "destination"}
    data, publish_model = publish.call_args.args
    assert data == {"model": "source", "copy_to": "destination"}
    assert publish_model.topic == SocketTopic.OllamaManager
    assert publish_model.topic_id == GLOBAL_TOPIC_ID
    assert publish_model.event == "settings:ollama:model:copied"
    assert publish_model.data_keys == ["model", "copy_to"]


def test_delete_model_treats_missing_model_as_completed(monkeypatch: MonkeyPatch, ollama_url: str) -> None:
    request = Mock(return_value=Mock(status_code=404))
    publish = Mock()
    monkeypatch.setattr(OllamaApi.requests, "delete", request)
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", publish)

    response = OllamaApi.delete_ollama_model(OllamaModelForm(model="old-model"))

    assert request.call_args.args == (f"{ollama_url}/api/delete",)
    assert request.call_args.kwargs["json"] == {"model": "old-model"}
    assert orjson.loads(response.body) == {"model": "old-model"}
    data, publish_model = publish.call_args.args
    assert data == {"model": "old-model"}
    assert publish_model.event == "settings:ollama:model:deleted"
    assert publish_model.data_keys == ["model"]


@pytest.mark.parametrize(
    ("operation", "status_code", "exception"),
    [
        ("copy", 404, ApiException.NotFound_404),
        ("copy", 500, ApiException.BadGateway_502),
        ("delete", 500, ApiException.BadGateway_502),
    ],
)
def test_ollama_failure_does_not_publish(
    monkeypatch: MonkeyPatch, ollama_url: str, operation: str, status_code: int, exception: type[Exception]
) -> None:
    publish = Mock()
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", publish)
    monkeypatch.setattr(OllamaApi.requests, "post", Mock(return_value=Mock(status_code=status_code)))
    monkeypatch.setattr(OllamaApi.requests, "delete", Mock(return_value=Mock(status_code=status_code)))

    with pytest.raises(exception):
        if operation == "copy":
            OllamaApi.copy_ollama_model(CopyOllamaModelForm(model="source", copy_to="destination"))
        else:
            OllamaApi.delete_ollama_model(OllamaModelForm(model="old-model"))

    publish.assert_not_called()


def test_ollama_network_failure_does_not_publish(monkeypatch: MonkeyPatch, ollama_url: str) -> None:
    publish = Mock()
    monkeypatch.setattr(OllamaApi.requests, "post", Mock(side_effect=requests.ConnectionError("unavailable")))
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", publish)

    with pytest.raises(ApiException.BadGateway_502):
        OllamaApi.copy_ollama_model(CopyOllamaModelForm(model="source", copy_to="destination"))

    publish.assert_not_called()


def test_broker_failure_is_not_acknowledged(monkeypatch: MonkeyPatch, ollama_url: str) -> None:
    monkeypatch.setattr(OllamaApi.requests, "post", Mock(return_value=Mock(status_code=200)))
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", Mock(side_effect=RuntimeError("broker down")))

    with pytest.raises(ApiException.ServiceUnavailable_503):
        OllamaApi.copy_ollama_model(CopyOllamaModelForm(model="source", copy_to="destination"))


def test_ollama_mutation_requires_configured_endpoint(monkeypatch: MonkeyPatch) -> None:
    previous = Env.OLLAMA_API_URL
    Env.update_env("OLLAMA_API_URL", None)
    request = Mock()
    monkeypatch.setattr(OllamaApi.requests, "post", request)
    try:
        with pytest.raises(ApiException.NotFound_404):
            OllamaApi.copy_ollama_model(CopyOllamaModelForm(model="source", copy_to="destination"))
    finally:
        Env.update_env("OLLAMA_API_URL", previous)
    request.assert_not_called()


def test_ollama_http_routes_enforce_auth_and_parse_delete_body(monkeypatch: MonkeyPatch, ollama_url: str) -> None:
    user = User.model_construct(id=SnowflakeID(1), is_admin=True, email="admin@example.com")

    def authenticate(scope: Scope) -> User | int:
        if Headers(scope=scope).get("authorization") != "Bearer access-token":
            return 401
        scope["auth"] = user
        return user

    monkeypatch.setattr(MiddlewareHelper, "validate_auth", authenticate)
    monkeypatch.setattr(RoleSecurity, "is_authorized", lambda self, user_id, path_params, actions, role_finder: True)
    monkeypatch.setattr(OllamaApi.requests, "delete", Mock(return_value=Mock(status_code=200)))
    monkeypatch.setattr(OllamaApi.BaseSocketPublisher, "put_dispather", Mock())

    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    client = TestClient(app)
    path = "/settings/ollama/models"
    body = {"model": "old-model"}

    assert client.request("DELETE", path, json=body).status_code == 401
    response = client.request("DELETE", path, json=body, headers={"Authorization": "Bearer access-token"})

    assert response.status_code == 200
    assert response.json() == body

    monkeypatch.setattr(RoleSecurity, "is_authorized", lambda self, user_id, path_params, actions, role_finder: False)
    assert client.request("DELETE", path, json=body, headers={"Authorization": "Bearer access-token"}).status_code == 403
