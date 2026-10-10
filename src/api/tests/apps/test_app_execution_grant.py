# ruff: noqa: F811
"""Current owner-app gates use actual SQLite authority rows, never app payload identity."""

import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import (
    CardAppOwnership,
    CardRelationship,
    GlobalCardRelationshipType,
    GraphApprovalRequest,
)
from langboard_shared.domain.models.bases import BaseGraphApprovalRequestModel
from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential
from langboard_shared.domain.services.AppExecutionGrant import evaluate_current_execution_grant
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppResources import set_card_app_resources
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.helpers import ModelHelper
from sqlalchemy import text
from test_card_app_resources import prepare


def grant_scope(board):
    connection, definition, binding, resources, card = prepare(board)
    engine = DbEngine.get_main_engine()
    models = (
        GlobalCardRelationshipType,
        CardRelationship,
        GraphApprovalRequest,
        *ModelHelper.get_models_by_base_class(BaseGraphApprovalRequestModel),
    )
    if engine.dialect.name == "postgresql":
        # Approval variants reference real bot/history tables. Include their FK
        # dependency closure rather than weakening PostgreSQL constraints.
        tables = set()

        def include(table):
            if table in tables:
                return
            tables.add(table)
            for foreign_key in table.foreign_keys:
                include(foreign_key.column.table)

        for model in models:
            include(model.__table__)
        models[0].metadata.create_all(engine, tables=list(tables), checkfirst=True)
    else:
        for model in models:
            model.__table__.create(engine)
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE card_execution_generation (card_id BIGINT PRIMARY KEY, execution_generation INTEGER NOT NULL)"
            )
        )
        db.execute(text("INSERT INTO card_execution_generation VALUES (:id, 3)"), {"id": int(card.id)})
    set_card_app_resources(board[1], board[2].id, card.id, connection.id, [resources[0].get_uid()], None)
    with DbSession.atomic() as db:
        definition.declaration = {**definition.declaration, "capabilities": ["resources.read", "execution.run"]}
        db.update(definition)
        binding.granted_capabilities = ["resources.read", "execution.run"]
        binding.stage_transitions_enabled = True
        binding.workflow_mapping = {"ready": board[5][0].get_uid()}
        db.update(binding)
        board[5][0].workflow_stage = "ready"
        db.update(board[5][0])
        board[6][0].key = "ready"
        board[6][0].is_builtin = True
        db.update(board[6][0])
        db.insert(CardAppOwnership(card_id=card.id, app_key=connection.app_key))
    token = issue_connection_credential(board[1], connection.id)["token"]
    return connection, definition, binding, resources, card, token


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_current_owner_grant_and_explicit_generation(board):
    connection, _, _, resources, card, token = grant_scope(board)
    result = evaluate_current_execution_grant(token, board[2].id, card.id, 3)
    assert result["generation"] == 3
    assert result["connection_uid"] == connection.get_uid()
    assert result["resource_uids"] == [resources[0].get_uid()]
    assert result["app_key"] == connection.app_key
    with pytest.raises(AppGovernanceDenied):
        evaluate_current_execution_grant(token, board[2].id, card.id, 2)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize(
    "gate",
    [
        "owner",
        "consent",
        "resource",
        "selection",
        "stage",
        "archive",
        "private",
        "mapping",
        "declaration",
        "revocation",
    ],
)
def test_current_gate_changes_deny_immediately(board, gate):
    from langboard_shared.core.db import SqlBuilder
    from langboard_shared.domain.models import CardAppResourceSelection

    connection, definition, binding, resources, card, token = grant_scope(board)
    assert evaluate_current_execution_grant(token, board[2].id, card.id, 3)["generation"] == 3
    with DbSession.atomic() as db:
        if gate == "owner":
            row = db.exec(SqlBuilder.select.table(CardAppOwnership)).first()
            row.app_key = "other-app"
        elif gate == "selection":
            row = db.exec(SqlBuilder.select.table(CardAppResourceSelection)).first()
            row.resource_uids = []
        elif gate == "consent":
            row = binding
            row.granted_capabilities = ["resources.read"]
        elif gate == "resource":
            row = resources[0]
            row.access_state = "revoked"
        elif gate == "stage":
            row = board[5][0]
            row.workflow_stage = "active"
        elif gate == "mapping":
            row = binding
            row.workflow_mapping = {}
        elif gate == "archive":
            from langboard_shared.core.types import SafeDateTime

            row = card
            row.archived_at = SafeDateTime.now()
        elif gate == "private":
            row = card
            row.visibility = "PRIVATE"
            row.created_by_user_id = row.owner_user_id = board[1].id
        elif gate == "declaration":
            row = definition
            row.declaration = {**row.declaration, "capabilities": ["resources.read"]}
        else:
            row = connection
            row.state = "disconnected"
        db.update(row)
    with pytest.raises(AppGovernanceDenied):
        evaluate_current_execution_grant(token, board[2].id, card.id, 3)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_dependency_and_pending_native_approval_fence(board):
    from langboard_shared.domain.models import Card, ManualScopeRunGraphApprovalRequest
    from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalRequestType

    _, _, _, _, card, token = grant_scope(board)
    with DbSession.atomic() as db:
        kind = GlobalCardRelationshipType(parent_name="blocks", child_name="blocked by", machine_semantic="blocks")
        db.insert(kind)
        prerequisite = Card(
            project_id=board[2].id, project_column_id=board[5][0].id, title="Pending", visibility="SHARED"
        )
        db.insert(prerequisite)
        edge = CardRelationship(card_id_child=card.id, card_id_parent=prerequisite.id, relationship_type_id=kind.id)
        db.insert(edge)
    with pytest.raises(AppGovernanceDenied):
        evaluate_current_execution_grant(token, board[2].id, card.id, 3)
    with DbSession.atomic() as db:
        db.delete(edge)
        request = GraphApprovalRequest(thread_id="test", request_type=GraphApprovalRequestType.ManualScopeRun)
        db.insert(request)
        db.insert(
            ManualScopeRunGraphApprovalRequest(approval_request_id=request.id, scope_table="card", scope_id=card.id)
        )
    with pytest.raises(AppGovernanceDenied):
        evaluate_current_execution_grant(token, board[2].id, card.id, 3)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_authority_http_does_not_start_or_accept_payload_identity(board):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.routes.settings import AppExecutionAuthorityApi  # noqa: F401
    from langboard_shared.core.routing import AppRouter

    _, _, binding, _, card, token = grant_scope(board)
    app = FastAPI()
    app.include_router(AppRouter.api)
    path = f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-authority"
    with TestClient(app) as client:
        assert client.get(path, params={"generation": 3}).status_code == 401
        assert (
            client.get(path, params={"generation": 3}, headers={"Authorization": "Bearer invalid"}).status_code == 401
        )
        headers = {"Authorization": f"Bearer {token}", "X-App-Key": "other-app"}
        response = client.get(path, params={"generation": 3}, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["state"] == "eligible" and response.json()["started"] is False
        assert response.json()["app_key"] != "other-app"
        assert client.get(path, params={"generation": 2}, headers=headers).status_code == 403
        with DbSession.atomic() as db:
            binding.granted_capabilities = ["resources.read"]
            db.update(binding)
        assert client.get(path, params={"generation": 3}, headers=headers).status_code == 403
        assert client.get(path, params={"generation": 0}, headers=headers).status_code == 400
