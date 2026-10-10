"""Socket audiences use current card policy, never subscription-time membership."""
import importlib
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt import encode
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.notification.NotificationApi import socket_card_dispatch_context
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Bot, ProjectAssignedUser, ProjectRole, User
from langboard_shared.Env import Env


@pytest.mark.parametrize("current_card", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize("credential", ["socket_dispatch", "bot", "missing", "expired"])
def test_socket_dispatch_checks_current_recipient_and_internal_credential(current_card, monkeypatch, credential):
    owner, project, card, card_service = current_card
    Bot.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        outsider = User(firstname="External", lastname="Actor", email="external@example.invalid",
                        password="test-only", activated_at=SafeDateTime.now())
        db.insert(outsider)
        membership = ProjectAssignedUser(project_id=project.id, user_id=outsider.id)
        db.insert(membership)
    service = SimpleNamespace(card=card_service, close=lambda: None)
    monkeypatch.setattr(importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service)
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is socket_card_dispatch_context:
            for dep in route.dependant.dependencies:
                if dep.name == "service":
                    app.dependency_overrides[dep.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    token = encode({"sub": str(owner.id), "internal": credential, "api_permission_level": "read",
                    "exp": int(SafeDateTime.now().timestamp()) + (-300 if credential == "expired" else 300),
                    "iss": Env.PROJECT_NAME}, Env.JWT_SECRET_KEY, algorithm=Env.JWT_ALGORITHM)
    headers = {} if credential == "missing" else {"X-Api-Token": token}
    body = {"card_uids": [card.get_uid()], "recipient_uids": [owner.get_uid(), outsider.get_uid()]}
    with TestClient(app) as client:
        response = client.post("/socket/card-dispatch-context", json=body, headers=headers)
        if credential != "socket_dispatch":
            assert response.status_code in (401, 403, 422)
            return
        assert response.status_code == 200
        assert response.json() == {"allowed_recipient_uids": [owner.get_uid()]}
        edit = {**body, "operation": "edit"}
        assert client.post("/socket/card-dispatch-context", json=edit, headers=headers).json() == {
            "allowed_recipient_uids": []}
        with DbSession.use(readonly=False) as db:
            role = ProjectRole(project_id=project.id, user_id=owner.id, actions=["read", "card_update"])
            db.insert(role)
        assert client.post("/socket/card-dispatch-context", json=edit, headers=headers).json() == {
            "allowed_recipient_uids": [owner.get_uid()]}
        with DbSession.use(readonly=False) as db:
            role.actions = ["read"]
            db.update(role)
        assert client.post("/socket/card-dispatch-context", json=edit, headers=headers).json() == {
            "allowed_recipient_uids": []}
        invalid = {**body, "card_uids": ["invalid-code!"]}
        assert client.post("/socket/card-dispatch-context", json=invalid, headers=headers).json() == {
            "allowed_recipient_uids": []}
        oversized = {**body, "recipient_uids": [owner.get_uid()] * 101}
        assert client.post("/socket/card-dispatch-context", json=oversized, headers=headers).status_code == 400
        empty = {**body, "card_uids": []}
        assert client.post("/socket/card-dispatch-context", json=empty, headers=headers).status_code == 400
        with DbSession.use(readonly=False) as db:
            card.visibility = "SHARED"
            card.owner_user_id = None
            db.update(card)
        assert client.post("/socket/card-dispatch-context", json=body, headers=headers).json() == {
            "allowed_recipient_uids": [owner.get_uid(), outsider.get_uid()]}
        with DbSession.use(readonly=False) as db:
            card.visibility = "INTERNAL"
            db.update(card)
        assert client.post("/socket/card-dispatch-context", json=body, headers=headers).json() == {
            "allowed_recipient_uids": []}
        with DbSession.use(readonly=False) as db:
            card.visibility = "SHARED"
            db.update(card)
            db.delete(membership)
        assert client.post("/socket/card-dispatch-context", json=body, headers=headers).json() == {
            "allowed_recipient_uids": [owner.get_uid()]}
        removal = {**body, "operation": "remove"}
        assert client.post("/socket/card-dispatch-context", json=removal, headers=headers).json() == {
            "allowed_recipient_uids": []}
        with DbSession.use(readonly=False) as db:
            card.visibility = "PRIVATE"
            card.owner_user_id = owner.id
            card.deleted_at = SafeDateTime.now()
            db.update(card)
        assert client.post("/socket/card-dispatch-context", json=body, headers=headers).json() == {
            "allowed_recipient_uids": []}
        assert client.post("/socket/card-dispatch-context", json=removal, headers=headers).json() == {
            "allowed_recipient_uids": [owner.get_uid()]}
        with DbSession.use(readonly=False) as db:
            owner.activated_at = None
            db.update(owner)
        assert client.post("/socket/card-dispatch-context", json=body, headers=headers).json() == {
            "allowed_recipient_uids": []}
