"""Receipt routes use current stored project roles before any receipt access."""

import asyncio
import pytest
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board import ExecutionReceiptApi  # noqa: F401 - Register actual receipt routes.
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.models import Project, ProjectRole, User
from sqlalchemy import create_engine, text


@pytest.fixture
def receipt_roles(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectRole):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            actor = User(firstname="Receipt", lastname="Reader", email="receipt@example.invalid", password="test-only")
            db.insert(actor)
            project = Project(owner_id=actor.id, title="Receipt board")
            foreign = Project(owner_id=actor.id, title="Other board")
            db.insert(project)
            db.insert(foreign)
        yield engine, actor, project, foreign
    finally:
        engine.dispose()


def request(actor, project_uid, method):
    messages = []
    reached = []

    async def terminal(scope, receive, send):
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    suffix = "executions/1/receipt" if method == "PUT" else "executions/receipts"
    scope = {
        "type": "http",
        "method": method,
        "path": f"/projects/{project_uid}/cards/card/{suffix}",
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    if actor is not None:
        scope["auth"] = actor
    asyncio.run(RoleMiddleware(terminal, AppRouter.api.routes)(scope, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    return status, bool(reached)


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("actions", [[], ["read"], ["card_update"], ["read", "card_update"], ["*"]])
def test_receipt_read_and_write_require_their_current_stored_project_role(receipt_roles, method, actions):
    _, actor, project, _ = receipt_roles
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectRole(user_id=actor.id, project_id=project.id, actions=actions))
    required = "read" if method == "GET" else "card_update"
    allowed = required in actions or "*" in actions
    assert request(actor, project.get_uid(), method) == (200 if allowed else 403, allowed)


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_foreign_board_role_does_not_authorize_receipt_access(receipt_roles, method):
    _, actor, project, foreign = receipt_roles
    with DbSession.use(readonly=False) as db:
        db.insert(ProjectRole(user_id=actor.id, project_id=foreign.id, actions=["*"]))
    assert request(actor, project.get_uid(), method) == (403, False)


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_role_revocation_is_observed_on_the_next_receipt_request(receipt_roles, method):
    engine, actor, project, _ = receipt_roles
    with DbSession.use(readonly=False) as db:
        role = ProjectRole(user_id=actor.id, project_id=project.id, actions=["*"])
        db.insert(role)
    assert request(actor, project.get_uid(), method) == (200, True)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM project_role WHERE id=:id"), {"id": int(role.id)})
    assert request(actor, project.get_uid(), method) == (403, False)


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_anonymous_receipt_requests_do_not_reach_the_route(method):
    assert request(None, "board", method) == (401, False)
