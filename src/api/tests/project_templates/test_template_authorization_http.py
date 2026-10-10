import importlib
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.settings import ProjectTemplateSettingsApi
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.models import User
from langboard_shared.helpers import MiddlewareHelper


@pytest.fixture
def template_http(monkeypatch):
    """Exercise original route metadata and middleware; isolate identity and storage."""
    calls = []
    templates = SimpleNamespace(get_api_list=lambda: calls.append("list") or [{"name": "QA"}])
    service = SimpleNamespace(project_template=templates, close=lambda: None)
    actor = User.model_construct(id=1, is_admin=False)
    identity = {"value": actor}

    def validate(scope):
        scope["auth"] = identity["value"]
        return identity["value"]

    monkeypatch.setattr(MiddlewareHelper, "validate_auth", validate)
    module = importlib.import_module("langboard.middlewares.ApiAuthMiddleware")
    monkeypatch.setattr(module, "DomainService", lambda: service)
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in AppRouter.api.routes:
        if getattr(route, "endpoint", None) is ProjectTemplateSettingsApi.get_project_templates:
            for dependency in route.dependant.dependencies:
                app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    with TestClient(app) as client:
        yield client, identity, calls


@pytest.mark.parametrize("anonymous", [False, True])
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/settings/project-templates"),
        ("PUT", "/settings/project-templates/qa-template"),
        ("PUT", "/settings/project-templates/default"),
        ("GET", "/settings/project-template-bots"),
    ],
)
def test_template_admin_routes_reject_before_validation_or_storage(template_http, anonymous, method, path):
    client, identity, calls = template_http
    if anonymous:
        identity["value"] = 401
    response = client.request(method, path, json={})
    assert response.status_code == (401 if anonymous else 403)
    assert calls == []


def test_authenticated_nonadmin_can_list_templates(template_http):
    client, _, calls = template_http
    response = client.get("/settings/project-templates")
    assert response.status_code == 200
    assert response.json() == {"templates": [{"name": "QA"}]}
    assert calls == ["list"]


def test_anonymous_cannot_list_templates(template_http):
    client, identity, calls = template_http
    identity["value"] = 401
    assert client.get("/settings/project-templates").status_code == 401
    assert calls == []
