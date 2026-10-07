"""Exercise the dispatch route through the real socket-token authentication path."""
import importlib
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt import encode
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.notification.NotificationApi import notification_dispatch_context
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Bot, UserNotification
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.services.factory.NotificationService import NotificationService
from langboard_shared.Env import Env


@pytest.mark.parametrize("current_card", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize('credential', ['valid', 'missing', 'invalid', 'expired'])
def test_dispatch_http_real_internal_token_and_current_acl(current_card, monkeypatch, credential):
    user, project, card, card_service = current_card
    UserNotification.__table__.create(DbEngine.get_main_engine())
    Bot.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        card.visibility = 'SHARED'
        card.owner_user_id = None
        db.update(card)
        note = UserNotification(receiver_id=user.id, notifier_type='user', notifier_id=user.id,
            notification_type=NotificationType.MentionedInCard,
            record_list=[('project', project.id), ('card', card.id)])
        db.insert(note)
    notification = NotificationService(lambda _: card_service, lambda _: None, SimpleNamespace())
    service = SimpleNamespace(notification=notification, close=lambda: None)
    monkeypatch.setattr(importlib.import_module('langboard.middlewares.ApiAuthMiddleware'), 'DomainService', lambda: service)
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, 'endpoint', None) is notification_dispatch_context:
            for dep in route.dependant.dependencies:
                if dep.name == 'service':
                    app.dependency_overrides[dep.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    token = encode({'sub': str(user.id), 'internal': 'bot', 'api_permission_level': 'read',
        'exp': int(SafeDateTime.now().timestamp()) + (300 if credential != 'expired' else -300),
        'iss': Env.PROJECT_NAME}, Env.JWT_SECRET_KEY, algorithm=Env.JWT_ALGORITHM)
    headers = {} if credential == 'missing' else {'X-Api-Token': token if credential != 'invalid' else 'invalid'}
    with TestClient(app) as client:
        response = client.get(f'/notifications/{note.get_uid()}/dispatch-context', headers=headers)
        if credential != 'valid':
            assert response.status_code in (401, 422)
            return
        assert response.status_code == 200
        assert response.json()['allowed'] is True
        assert response.json()['recipient']['email'] == user.email
        with DbSession.use(readonly=False) as db:
            card.visibility = 'INTERNAL'
            db.update(card)
        denied = client.get(f'/notifications/{note.get_uid()}/dispatch-context', headers=headers)
        assert denied.status_code == 200
        assert denied.json() == {'allowed': False, 'recipient': None}

        with DbSession.use(readonly=False) as db:
            card.visibility = "SHARED"
            db.update(card)
            user.activated_at = None
            db.update(user)
        inactive = client.get(f"/notifications/{note.get_uid()}/dispatch-context", headers=headers)
        assert inactive.status_code == 200
        assert inactive.json() == {"allowed": False, "recipient": None}
