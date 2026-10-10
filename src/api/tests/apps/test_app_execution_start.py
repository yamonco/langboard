# ruff: noqa: F811
"""App-reported start is separate from authorization and rejects stale authority."""

import importlib
from datetime import timedelta
from secrets import token_hex
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import AppExecutionLease, AppExecutionStart
from langboard_shared.domain.services.AppExecutionLeases import authorize_app_runtime
from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict
from langboard_shared.domain.services.AppExecutionStarts import report_app_execution_start
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_execution_lease import permit_scope


def start_scope(board, monkeypatch):
    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    module = importlib.import_module("langboard.migrations.versions.20261011053000-cb5fa26349d1")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
    finally:
        module.op = original
    runtime_token = token_hex(32)
    permit = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    return connection, card, token, request, SnowflakeID.from_short_code(permit["lease_uid"]), runtime_token


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("gate", ["connection", "stage", "expiry", "token", "stopped"])
def test_stale_or_foreign_runtime_never_records_start(board, monkeypatch, gate):
    connection, card, token, request, lease_id, runtime_token = start_scope(board, monkeypatch)
    with DbSession.atomic() as db:
        if gate == "connection":
            connection.state = "revoked"
            db.update(connection)
        elif gate == "stage":
            board[5][0].workflow_stage = "active"
            db.update(board[5][0])
        elif gate in ("expiry", "stopped"):
            lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
            if gate == "expiry":
                lease.expires_at = SafeDateTime.now() - timedelta(seconds=1)
            else:
                lease.state = "stopped"
            db.update(lease)
    with pytest.raises(AppGovernanceDenied):
        report_app_execution_start(
            token,
            board[2].id,
            card.id,
            request.id,
            lease_id,
            token_hex(32) if gate == "token" else runtime_token,
            "process-1",
        )
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(AppExecutionStart)).all()


@pytest.mark.parametrize("board", ["sqlite://", "postgresql-test"], indirect=True)
def test_start_receipt_is_idempotent_and_does_not_mutate_card(board, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _, card, token, request, lease_id, runtime_token = start_scope(board, monkeypatch)

    def report(_):
        return report_app_execution_start(token, board[2].id, card.id, request.id, lease_id, runtime_token, "process-1")

    if DbEngine.get_main_engine().dialect.name == "postgresql":
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(report, range(4)))
    else:
        receipts = [report(0), report(1)]
    assert len({r["start_uid"] for r in receipts}) == 1
    assert sum(r["changed"] for r in receipts) == 1
    assert all(r["state"] == "start_reported" and r["evidence_kind"] == "app_attestation" for r in receipts)
    assert all(r["request_uid"] == request.get_uid() and r["lease_uid"] == lease_id.to_short_code() for r in receipts)
    with pytest.raises(AppExecutionRequestConflict):
        report_app_execution_start(token, board[2].id, card.id, request.id, lease_id, runtime_token, "process-2")
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(AppExecutionStart)).all()) == 1
    assert card.project_column_id == board[5][0].id


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_packaged_sdk_start_report_uses_native_http(board, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard_sdk import AppExecution, HttpTransport
    from langboard_shared.core.routing import AppRouter

    _, card, token, request, lease_id, runtime_token = start_scope(board, monkeypatch)
    app = FastAPI()
    app.include_router(AppRouter.api)
    with TestClient(app) as client:

        async def transport(method, path, **kwargs):
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=transport)))
        args = dict(
            request_uid=request.get_uid(),
            lease_uid=lease_id.to_short_code(),
            runtime_token=runtime_token,
            execution_reference="native-process-1",
        )
        first = await execution.report_start(board[2].get_uid(), card.get_uid(), **args)
        replay = await execution.report_start(board[2].get_uid(), card.get_uid(), **args)
        assert first["start_uid"] == replay["start_uid"] and replay["changed"] is False
        report = await execution.runtime_report(lease_id.to_short_code(), runtime_token)
        assert report["active_report"] is True and report["start_report"]["start_uid"] == first["start_uid"]
        with DbSession.atomic() as db:
            lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
            original_expiry = lease.expires_at
        await execution.runtime_report(lease_id.to_short_code(), runtime_token)
        with DbSession.atomic() as db:
            assert db.exec(SqlBuilder.select.table(AppExecutionLease)).first().expires_at == original_expiry
        path = f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-requests/{request.get_uid()}/start-reports"
        assert client.post(path, json={k: v for k, v in args.items() if k != "request_uid"}).status_code == 401


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_start_evidence_survives_source_removal_and_blocks_downgrade(board, monkeypatch):
    from langboard_shared.domain.models import AppExecutionRequest

    _, card, token, request, lease_id, runtime_token = start_scope(board, monkeypatch)
    receipt = report_app_execution_start(token, board[2].id, card.id, request.id, lease_id, runtime_token, "process-1")
    with DbSession.atomic() as db:
        lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        source = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
        db.delete(lease)
        db.delete(source)
        db.delete(card)
    with DbSession.atomic() as db:
        stored = db.exec(SqlBuilder.select.table(AppExecutionStart)).first()
        assert stored.get_uid() == receipt["start_uid"] and stored.execution_reference == "process-1"
        assert stored.request_id == request.id and stored.generation == request.generation
        assert stored.runtime_reference == "runtime-1"
    module = importlib.import_module("langboard.migrations.versions.20261011053000-cb5fa26349d1")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            with pytest.raises(RuntimeError, match="start evidence"):
                module.downgrade()
    finally:
        module.op = original


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_new_credential_cannot_take_over_existing_runtime_start(board, monkeypatch):
    from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential

    connection, card, _, request, lease_id, runtime_token = start_scope(board, monkeypatch)
    new_token = issue_connection_credential(board[1], connection.id)["token"]
    with pytest.raises(AppGovernanceDenied):
        report_app_execution_start(new_token, board[2].id, card.id, request.id, lease_id, runtime_token, "process-1")
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(AppExecutionStart)).all()


@pytest.mark.parametrize("board", ["sqlite://", "postgresql-test"], indirect=True)
@pytest.mark.parametrize("gate", ["revoked", "expired", "stopped"])
def test_runtime_report_does_not_renew_or_infer_started_and_keeps_revoked_evidence(board, monkeypatch, gate):
    from langboard_shared.domain.models import AppConnectionCredential
    from langboard_shared.domain.services.AppExecutionStarts import read_app_runtime_report

    _, card, token, request, lease_id, runtime_token = start_scope(board, monkeypatch)
    no_start = read_app_runtime_report(lease_id, runtime_token)
    assert no_start["active_report"] is False and no_start["start_report"] is None
    assert no_start["evidence_kind"] == "none" and no_start["started"] is False
    with DbSession.atomic() as db:
        lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        original_expiry = lease.expires_at
    report_app_execution_start(token, board[2].id, card.id, request.id, lease_id, runtime_token, "process-1")
    report = read_app_runtime_report(lease_id, runtime_token)
    assert report["active_report"] is True and report["evidence_kind"] == "app_attestation"
    assert report["started"] is False and report["start_report"]["execution_reference"] == "process-1"
    with DbSession.atomic() as db:
        lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        assert lease.expires_at == original_expiry
        credential = db.exec(
            SqlBuilder.select.table(AppConnectionCredential).where(AppConnectionCredential.id == lease.credential_id)
        ).first()
        if gate == "revoked":
            credential.revoked_at = SafeDateTime.now()
            db.update(credential)
        elif gate == "expired":
            lease.expires_at = SafeDateTime.now() - timedelta(seconds=1)
            db.update(lease)
        else:
            lease.state = "stopped"
            db.update(lease)
    revoked = read_app_runtime_report(lease_id, runtime_token)
    assert revoked["active_report"] is False and revoked["state"] == (
        "stopped" if gate == "stopped" else "stop_requested"
    )
    assert revoked["start_report"] == report["start_report"]
    with pytest.raises(AppGovernanceDenied):
        read_app_runtime_report(lease_id, token_hex(32))
