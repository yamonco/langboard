# ruff: noqa: F811
"""Native app reads do not inherit board scope from authenticated identity."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.routes.settings import AppConnectionResourcesApi  # noqa: F401
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.models import AppConnection, AppResourceBinding, BoardAppBinding, ProjectAssignedUser
from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential
from langboard_shared.domain.services.AppConnectionResources import list_connection_resources
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_connection_credentials import DECLARATION, setup


def scope(board):
    actor, project = board[1:3]
    connection, definition = setup(actor)
    with DbSession.atomic() as db:
        project.owner_id = actor.id
        db.update(project)
        definition.declaration = {**DECLARATION, "capabilities": ["resources.read"]}
        db.update(definition)
        binding = BoardAppBinding(
            project_id=project.id, app_key=connection.app_key, state="enabled", granted_capabilities=["resources.read"]
        )
        db.insert(binding)
        rows = [
            AppResourceBinding(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="issue",
                external_resource_id=str(i),
                access_state="granted",
            )
            for i in range(3)
        ]
        for row in rows:
            db.insert(row)
    return connection, definition, binding, rows, issue_connection_credential(actor, connection.id)["token"]


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_resource_paging_and_connection_isolation(board):
    connection, _, binding, rows, token = scope(board)
    with DbSession.atomic() as db:
        other = AppConnection(app_key=connection.app_key, owner_id=board[1].id, state="connected")
        db.insert(other)
        for kwargs in (
            {"connection_id": other.id},
            {"is_selected": False},
            {"access_state": "revoked"},
            {"resource_type": "undeclared"},
        ):
            values = dict(
                board_binding_id=binding.id,
                connection_id=connection.id,
                resource_type="issue",
                external_resource_id=str(kwargs),
                access_state="granted",
            )
            db.insert(AppResourceBinding(**{**values, **kwargs}))
    app = FastAPI()
    app.include_router(AppRouter.api)
    path = f"/apps/v1/boards/{board[2].get_uid()}/resources"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        headers = {"Authorization": f"Bearer {token}", "X-App-Key": "other"}
        first = client.get(path, headers=headers, params={"limit": 2})
        assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
        assert len(first.json()["items"]) == 2
        second = client.get(path, headers=headers, params={"after": first.json()["next_cursor"], "limit": 2})
        assert second.status_code == 200 and len(second.json()["items"]) == 1
        assert second.json()["items"][0]["resource_uid"] == rows[-1].get_uid()
        assert second.json()["next_cursor"] is None
        with DbSession.atomic() as db:
            binding.granted_capabilities = []
            db.update(binding)
        assert client.get(path, headers=headers).status_code == 403
        assert client.get(path, headers=headers, params={"limit": 51}).status_code == 400
        assert (
            client.get(
                f"/apps/v1/boards/{board[2].get_uid()}/resources", headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("gate", ["consent", "binding", "declaration", "shared", "organization", "project"])
def test_current_board_authority_revocation(board, gate):
    _, definition, binding, _, token = scope(board)
    assert len(list_connection_resources(token, board[2].id)["items"]) == 3
    with DbSession.atomic() as db:
        if gate == "consent":
            binding.granted_capabilities = []
            db.update(binding)
        elif gate == "binding":
            binding.state = "disabled"
            db.update(binding)
        elif gate == "declaration":
            definition.declaration = {**DECLARATION, "capabilities": []}
            db.update(definition)
        elif gate == "shared":
            db.insert(ProjectAssignedUser(project_id=board[2].id, user_id=2))
        elif gate == "organization":
            board[2].organization_id = 999
            db.update(board[2])
        elif gate == "project":
            from langboard_shared.core.types import SafeDateTime

            board[2].deleted_at = SafeDateTime.now()
            db.update(board[2])
    with pytest.raises(AppGovernanceDenied):
        list_connection_resources(token, board[2].id)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("gate", [None, "role", "organization", "member", "foreign"])
def test_organization_connection_preserves_current_board_authority(board, gate):
    from langboard_shared.domain.models import Organization

    Organization.__table__.create(DbEngine.get_main_engine())
    connection, _, _, _, _ = scope(board)
    with DbSession.atomic() as db:
        organization = Organization(name="Shared organization", slug="shared", owner_user_id=board[1].id)
        db.insert(organization)
        connection.ownership = "organization"
        connection.organization_id = organization.id
        db.update(connection)
        board[2].organization_id = organization.id
        board[2].owner_id = 2
        db.update(board[2])
    token = issue_connection_credential(board[1], connection.id)["token"]
    assert len(list_connection_resources(token, board[2].id)["items"]) == 3
    if gate is None:
        return
    with DbSession.atomic() as db:
        if gate == "role":
            board[4].actions = []
            db.update(board[4])
        elif gate == "member":
            db.delete(board[3])
        elif gate == "foreign":
            board[2].organization_id = 999
            db.update(board[2])
        else:
            organization.is_active = False
            db.update(organization)
    with pytest.raises(AppGovernanceDenied):
        list_connection_resources(token, board[2].id)
