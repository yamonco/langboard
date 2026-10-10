"""Current project read authorization guards bounded history reconciliation."""

import asyncio
from types import SimpleNamespace
import pytest
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board.BoardCardApi import get_available_recent_cards
from langboard.routes.dashboard.DashboardForm import RecentCardsAvailabilityForm
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.models import Project, ProjectRole, User
from langboard_shared.filter import RoleFilter
from pydantic import ValidationError
from sqlalchemy import create_engine


@pytest.mark.parametrize(
    "actions,foreign,expected",
    [([], False, 403), (["read"], False, 200), (["card_update"], False, 403), (["read"], True, 403)],
)
def test_route_uses_actual_current_project_read_role(monkeypatch, actions, foreign, expected):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectRole):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            user = User(
                firstname="Recent", lastname="Reader", email="recent-reader@example.invalid", password="test-only"
            )
            db.insert(user)
            project = Project(owner_id=user.id, title="Current")
            other = Project(owner_id=user.id, title="Other")
            db.insert(project)
            db.insert(other)
            db.insert(ProjectRole(user_id=user.id, project_id=other.id if foreign else project.id, actions=actions))
        assert _request(user, project.get_uid()) == expected
        assert RoleFilter.get_filtered(get_available_recent_cards)[1] == ["read"]
        assert AuthFilter.get_filtered(get_available_recent_cards) == "user"
    finally:
        engine.dispose()


def _request(actor, project_uid):
    messages = []

    async def terminal(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/board/{project_uid}/cards/available",
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    if actor is not None:
        scope["auth"] = actor
    asyncio.run(RoleMiddleware(terminal, AppRouter.api.routes)(scope, receive, send))
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def test_anonymous_never_reaches_history_read():
    assert _request(None, "project-a") == 401


@pytest.mark.parametrize("uids", [[""], ["a" * 33], ["a"] * 201])
def test_invalid_or_unbounded_input_is_rejected(uids):
    with pytest.raises(ValidationError):
        RecentCardsAvailabilityForm(card_uids=uids)


def test_route_forwards_only_requested_ids_to_scoped_service():
    calls = []
    service = SimpleNamespace(
        card=SimpleNamespace(get_existing_uids=lambda project, uids: calls.append((project, uids)) or ["one"])
    )
    response = get_available_recent_cards("project", RecentCardsAvailabilityForm(card_uids=["one", "missing"]), service)
    assert calls == [("project", ["one", "missing"])]
    assert response.body == b'{"card_uids":["one"]}'
