"""The HTTP dock command uses board-setting authority, not card-write authority."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.middlewares.RoleMiddleware import RoleMiddleware
from langboard.routes.board.BoardColumnApi import get_project_column_dock, replace_project_column_dock
from langboard.routes.board.forms.Column import ReplaceColumnDockForm
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiException, AppRouter
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import ProjectRole, User
from langboard_shared.domain.models.ProjectColumn import ProjectColumnDockConflict
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleSecurity
from pydantic import ValidationError


@pytest.mark.parametrize(
    "actions,expected", [([], 403), (["read"], 403), (["card_write", "card_update"], 403), (["update"], 200)]
)
def test_dock_http_authority(monkeypatch: pytest.MonkeyPatch, actions, expected):
    calls = []

    def decision(self, user_id, path_params, required, finder):
        calls.append((self._model_class, user_id, path_params, required))
        return set(required).issubset(actions)

    monkeypatch.setattr(RoleSecurity, "is_authorized", decision)
    result = _request(
        User(id=SnowflakeID(1), firstname="Dock", lastname="Test", email="dock@example.invalid", password="test-only")
    )
    assert result == expected
    assert calls == [(ProjectRole, SnowflakeID(1), {"project_uid": "project-a"}, ["update"])]
    assert AuthFilter.get_filtered(replace_project_column_dock) == "user"
    assert RoleFilter.get_filtered(replace_project_column_dock)[1] == ["update"]


def test_missing_auth_never_reaches_dock_command():
    assert _request(None) == 401


def _request(actor, method="PUT"):
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
        "method": method,
        "path": "/board/project-a/column/dock",
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    if actor is not None:
        scope["auth"] = actor
    middleware = RoleMiddleware(terminal, AppRouter.api.routes)
    asyncio.run(middleware(scope, receive, send))
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


@pytest.mark.parametrize("actions,expected", [([], 403), (["read"], 200), (["update"], 403), (["card_write"], 403)])
def test_read_dock_requires_board_read_authority(monkeypatch: pytest.MonkeyPatch, actions, expected):
    required_actions = []

    def decision(self, user_id, path_params, required, finder):
        required_actions.append(required)
        return set(required).issubset(actions)

    monkeypatch.setattr(RoleSecurity, "is_authorized", decision)
    actor = User(
        id=SnowflakeID(1), firstname="Dock", lastname="Test", email="dock@example.invalid", password="test-only"
    )
    assert _request(actor, "GET") == expected
    assert required_actions == [["read"]]
    assert RoleFilter.get_filtered(get_project_column_dock)[1] == ["read"]


def test_read_dock_without_auth_is_rejected():
    assert _request(None, "GET") == 401


@pytest.mark.parametrize("snapshot", [None, {"column_uids": [], "revision": 0}])
def test_read_dock_returns_snapshot_or_missing_project(snapshot):
    read = Mock(return_value=snapshot)
    service = SimpleNamespace(project_column=SimpleNamespace(get_dock_snapshot=read))
    if snapshot is None:
        with pytest.raises(ApiException.NotFound_404):
            get_project_column_dock("project-a", service)
    else:
        response = get_project_column_dock("project-a", service)
        assert response.status_code == 200
        assert b'"column_uids":[]' in response.body
        assert b'"revision":0' in response.body
    read.assert_called_once_with("project-a")


def test_dock_route_passes_whole_list_and_returns_committed_revision():
    command = Mock(return_value={"column_uids": ["c", "a"], "revision": 3})
    response = replace_project_column_dock(
        "project-a",
        ReplaceColumnDockForm(column_uids=["c", "a"], expected_revision=2),
        SimpleNamespace(project_column=SimpleNamespace(replace_dock_columns=command)),
    )
    command.assert_called_once_with("project-a", ["c", "a"], 2)
    assert response.status_code == 200
    assert b'"revision":3' in response.body


def test_rejected_dock_does_not_return_partial_configuration():
    command = Mock(return_value=None)
    with pytest.raises(ApiException.NotFound_404):
        replace_project_column_dock(
            "project-a",
            ReplaceColumnDockForm(column_uids=["foreign"], expected_revision=0),
            SimpleNamespace(project_column=SimpleNamespace(replace_dock_columns=command)),
        )


@pytest.mark.parametrize("revision", [None, -1, True, 1.5, "1"])
def test_dock_revision_is_required_and_strict(revision):
    arguments = {"column_uids": []}
    if revision is not None:
        arguments["expected_revision"] = revision
    with pytest.raises(ValidationError):
        ReplaceColumnDockForm(**arguments)


def test_stale_dock_is_a_conflict_not_a_missing_board():
    command = Mock(side_effect=ProjectColumnDockConflict())
    with pytest.raises(ApiException.Conflict_409) as error:
        replace_project_column_dock(
            "project-a",
            ReplaceColumnDockForm(column_uids=[], expected_revision=0),
            SimpleNamespace(project_column=SimpleNamespace(replace_dock_columns=command)),
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "EX2001"
