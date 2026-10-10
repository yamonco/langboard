# ruff: noqa: F811
"""Accepted requests survive deletion and never fabricate started runtime proof."""

import importlib
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.routes.settings import AppExecutionAuthorityApi  # noqa: F401
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.domain.models import AppExecutionRequest
from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict, request_app_execution
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_execution_grant import grant_scope


def prepare(board):
    state = grant_scope(board)
    module = importlib.import_module("langboard.migrations.versions.20261011031000-c59f460783db")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
    finally:
        module.op = original
    return state


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_duplicate_and_revocation_keep_receipt(board):
    _, _, binding, _, card, token = prepare(board)
    app = FastAPI()
    app.include_router(AppRouter.api)
    path = f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-requests"
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        assert client.post(path, json={"generation": 3}).status_code == 401
        assert client.post(path, json={"generation": True}, headers=headers).status_code == 400
        assert client.post(path, json={"generation": 3, "app_key": "other"}, headers=headers).status_code == 400
        first = client.post(path, json={"generation": 3}, headers=headers)
        assert first.status_code == 200 and first.json()["changed"] is True
        assert first.json()["started"] is False and first.json()["state"] == "requested"
        second = client.post(path, json={"generation": 3}, headers=headers)
        assert second.status_code == 200 and second.json()["changed"] is False
        assert second.json()["request_uid"] == first.json()["request_uid"]
        with DbSession.atomic() as db:
            binding.granted_capabilities = []
            db.update(binding)
        assert client.post(path, json={"generation": 3}, headers=headers).status_code == 403
    with DbSession.atomic() as db:
        rows = db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()
        assert len(rows) == 1 and rows[0].authority["generation"] == 3
        assert rows[0].authority["resource_uids"]
        db.delete(card, purge=True)
    module = importlib.import_module("langboard.migrations.versions.20261011031000-c59f460783db")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            with pytest.raises(RuntimeError, match="request history"):
                module.downgrade()
    finally:
        module.op = original


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_conflicting_identity_and_storage_failure_are_not_success(board, monkeypatch):
    _, _, _, _, card, token = prepare(board)
    original = DbSession.insert

    def insert(db, row):
        if isinstance(row, AppExecutionRequest):
            raise RuntimeError("receipt unavailable")
        return original(db, row)

    monkeypatch.setattr(DbSession, "insert", insert)
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        request_app_execution(token, board[2].id, card.id, 3)
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()
    monkeypatch.setattr(DbSession, "insert", original)
    request_app_execution(token, board[2].id, card.id, 3)
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
        row.connection_id += 1
        db.update(row)
    with pytest.raises(AppExecutionRequestConflict):
        request_app_execution(token, board[2].id, card.id, 3)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_changed_selection_requires_new_generation_even_when_still_authorized(board):
    from langboard_shared.domain.services.CardAppResources import set_card_app_resources

    connection, _, _, resources, card, token = prepare(board)
    first = request_app_execution(token, board[2].id, card.id, 3)
    set_card_app_resources(board[1], board[2].id, card.id, connection.id, [resources[1].get_uid()], 1)
    with pytest.raises(AppExecutionRequestConflict):
        request_app_execution(token, board[2].id, card.id, 3)
    with DbSession.atomic() as db:
        rows = db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()
        assert len(rows) == 1 and rows[0].get_uid() == first["request_uid"]
        assert rows[0].authority["resource_uids"] == [resources[0].get_uid()]
