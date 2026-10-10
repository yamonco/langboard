# ruff: noqa: F811
"""Native app receipt readback and idempotent reception acknowledgment."""

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
from langboard_shared.domain.models import AppExecutionAcknowledgment, AppExecutionOutbox, AppExecutionRequest
from langboard_shared.domain.services.AppEventDelivery import claim_app_event, finish_app_event
from langboard_shared.domain.services.AppEventDestination import bind_app_event_destination
from langboard_shared.domain.services.AppExecutionAcknowledgments import (
    acknowledge_app_execution,
    read_app_execution_request,
)
from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401


def scope(board, monkeypatch):
    from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential
    from test_app_event_destination import destination_scope

    connection, _, setting, event = destination_scope(board)
    module = importlib.import_module("langboard.migrations.versions.20261011043000-a93d804127bf")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
    finally:
        module.op = original
    bind_app_event_destination(board[1], connection.id, setting.id, None)
    from langboard_shared.core.security import KeyVault

    monkeypatch.setattr(KeyVault, "get_key", lambda _: "secret")
    token = issue_connection_credential(board[1], connection.id)["token"]
    from langboard_shared.domain.models import Card

    with DbSession.atomic() as db:
        card = db.exec(SqlBuilder.select.table(Card)).first()
    return connection, card, token, event


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_ack_is_received_only_and_idempotent(board, monkeypatch):
    _, card, token, event = scope(board, monkeypatch)
    claim = claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
    first = acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "runtime-1")
    second = acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "runtime-1")
    assert first["state"] == second["state"] == "received" and first["started"] is False and second["changed"] is False
    assert read_app_execution_request(token, board[2].id, card.id, request.id)["started"] is False
    with pytest.raises(AppExecutionRequestConflict):
        acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "runtime-2")
    finish_app_event(event.id, claim["claim_token"], delivered=True)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_ack_requires_delivered_or_live_claim(board, monkeypatch):
    _, card, token, event = scope(board, monkeypatch)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
    with pytest.raises(AppGovernanceDenied):
        acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "runtime")


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_ack_http_requires_app_auth_and_replays_receipt(board, monkeypatch):
    _, card, token, event = scope(board, monkeypatch)
    claim = claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
    app = FastAPI()
    app.include_router(AppRouter.api)
    path = f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-requests/{request.get_uid()}/acknowledgments"
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        assert client.post(path, json={"event_uid": event.get_uid(), "runtime_reference": "runtime"}).status_code == 401
        assert (
            client.post(
                path, json={"event_uid": event.get_uid(), "runtime_reference": "runtime"}, headers=headers
            ).json()["changed"]
            is True
        )
        assert (
            client.get(
                f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-requests/{request.get_uid()}",
                headers=headers,
            ).json()["started"]
            is False
        )
    finish_app_event(event.id, claim["claim_token"], delivered=True)


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
@pytest.mark.parametrize("change", ["connection", "stage", "event", "expiry"])
def test_changed_scope_cannot_acknowledge_or_mutate_history(board, monkeypatch, change):
    from datetime import timedelta
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import AppExecutionAcknowledgment, AppExecutionRequest

    connection, card, token, event = scope(board, monkeypatch)
    claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
        if change == "connection":
            connection.state = "revoked"
            db.update(connection)
        elif change == "stage":
            board[5][0].workflow_stage = "active"
            db.update(board[5][0])
        elif change == "expiry":
            row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
            row.lease_until = SafeDateTime.now() - timedelta(seconds=1)
            db.update(row)
    with pytest.raises(AppGovernanceDenied):
        acknowledge_app_execution(
            token, board[2].id, card.id, request.id, event.id + 1 if change == "event" else event.id, "runtime"
        )
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(AppExecutionAcknowledgment)).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_packaged_sdk_readback_and_ack_use_native_routes(board, monkeypatch):
    from types import SimpleNamespace
    from langboard_sdk import AppExecution, HttpTransport

    _, card, token, event = scope(board, monkeypatch)
    claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
    app = FastAPI()
    app.include_router(AppRouter.api)
    with TestClient(app) as client:

        async def transport(method, path, **kwargs):
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=transport)))
        args = board[2].get_uid(), card.get_uid()
        readback = await execution.read_request(*args, request_uid=request.get_uid())
        assert readback["authority"] == request.authority and readback["started"] is False
        first = await execution.acknowledge(
            *args, request_uid=request.get_uid(), event_uid=event.get_uid(), runtime_reference="native-sdk-runtime"
        )
        second = await execution.acknowledge(
            *args, request_uid=request.get_uid(), event_uid=event.get_uid(), runtime_reference="native-sdk-runtime"
        )
        assert first["acknowledgment_uid"] == second["acknowledgment_uid"]
        assert first["state"] == "received" and first["started"] is False
        assert first["changed"] is True and second["changed"] is False


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_postgres_concurrent_ack_persists_one_received_receipt(board, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _, card, token, event = scope(board, monkeypatch)
    claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()

    def acknowledge(_):
        return acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "same-runtime")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(acknowledge, range(4)))
    assert len({result["acknowledgment_uid"] for result in results}) == 1
    assert sum(result["changed"] for result in results) == 1
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(AppExecutionAcknowledgment)).all()) == 1
