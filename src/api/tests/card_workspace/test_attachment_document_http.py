"""Exercise native HTTP authentication and project update authorization."""

import importlib
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board import BoardCardAttachmentApi
from langboard_shared.core.routing import ApiException, AppRouter
from langboard_shared.domain.models import User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.helpers import MiddlewareHelper
from langboard_shared.security import RoleSecurity


@pytest.fixture
def document_http(monkeypatch):
    calls = []
    state = {
        "actor": User.model_construct(id=1, is_admin=False, email="fixture@example.invalid"),
        "allowed": False,
        "result": "pending",
        "visible": True,
        "child_valid": True,
    }

    def process(project, card, attachment, *, reprocess):
        calls.append((project, card, attachment, reprocess))
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    def resolve_card(project, card, actor, channel):
        assert (project, card, actor) == ("board", "card", state["actor"])
        return (object(), SimpleNamespace(id=1), object()) if state["visible"] else None

    def validate_child(card, model, uid):
        assert card.id == 1 and uid == "source"
        if not state["child_valid"]:
            raise ApiException.NotFound_404()

    monkeypatch.setattr(BoardCardAttachmentApi, "require_card_child", validate_child)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=resolve_card), card_attachment=SimpleNamespace(request_document_processing=process), close=lambda: None)

    def validate(scope, *, allow_oidc=False):
        assert allow_oidc is False
        scope["auth"] = state["actor"]
        return state["actor"]

    def authorize(self, user_id, path_params, actions, finder):
        assert actions == [ProjectRoleAction.CardUpdate.value]
        assert path_params["project_uid"] == "board"
        return state["allowed"]

    monkeypatch.setattr(MiddlewareHelper, "validate_auth", validate)
    monkeypatch.setattr(RoleSecurity, "is_authorized", authorize)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in AppRouter.api.routes:
        if getattr(route, "endpoint", None) is BoardCardAttachmentApi.process_card_attachment_document:
            for dependency in route.dependant.dependencies:
                if dependency.name == "service":
                    app.dependency_overrides[dependency.call] = lambda: service
    app.add_middleware(RoleMiddleware, routes=AppRouter.api.routes)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    with TestClient(app) as client:
        yield client, state, calls


def test_document_processing_http_rejects_unauthorized_before_enqueue(document_http):
    client, state, calls = document_http
    path = "/board/board/card/card/attachment/source/document-processing"
    assert client.post(path, json={"reprocess": True}).status_code == 403
    assert calls == []
    state["actor"] = 401
    assert client.post(path, json={"reprocess": True}).status_code == 401
    assert calls == []


def test_document_processing_http_preserves_scope_and_handles_rejection(document_http):
    client, state, calls = document_http
    state["allowed"] = True
    path = "/board/board/card/card/attachment/source/document-processing"
    response = client.post(path, json={"reprocess": True})
    assert response.status_code == 200
    assert response.json() == {"status": "pending"}
    assert calls == [("board", "card", "source", True)]
    state["result"] = None
    assert client.post(path, json={}).status_code == 404
    state["result"] = ValueError("Provider not configured")
    assert client.post(path, json={}).status_code == 400


@pytest.mark.parametrize("invalid", ["visible", "child_valid"])
def test_document_http_card_or_child_denial_never_enqueues(document_http, invalid):
    client, state, calls = document_http
    state["allowed"] = True
    state[invalid] = False
    assert client.post("/board/board/card/card/attachment/source/document-processing", json={}).status_code == 404
    assert calls == []
