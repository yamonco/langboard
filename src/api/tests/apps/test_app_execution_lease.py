# ruff: noqa: F811
"""Current-authority permits expire and revoked runtimes retain stop-only receipts."""

import importlib
from datetime import timedelta
from secrets import token_hex
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import AppExecutionLease, AppExecutionRequest
from langboard_shared.domain.services.AppEventDelivery import _expired, claim_app_event
from langboard_shared.domain.services.AppExecutionAcknowledgments import acknowledge_app_execution
from langboard_shared.domain.services.AppExecutionLeases import authorize_app_runtime, check_app_runtime
from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_execution_ack import scope


def permit_scope(board, monkeypatch):
    connection, card, token, event = scope(board, monkeypatch)
    module = importlib.import_module("langboard.migrations.versions.20261011050000-ba4e915238c0")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
    finally:
        module.op = original
    fence = importlib.import_module("langboard.migrations.versions.20261011060000-dc60b3745ae2")
    original_fence_op = fence.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            fence.op = Operations(MigrationContext.configure(db))
            fence.upgrade()
    finally:
        fence.op = original_fence_op
    claim_app_event(event.id, 1)
    with DbSession.atomic() as db:
        request = db.exec(SqlBuilder.select.table(AppExecutionRequest)).first()
    ack = acknowledge_app_execution(token, board[2].id, card.id, request.id, event.id, "runtime-1")
    from langboard_shared.core.types import SnowflakeID

    return connection, card, token, request, SnowflakeID.from_short_code(ack["acknowledgment_uid"])


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("change", ["connection", "stage", "expiry"])
def test_permit_revocation_and_stop_only_history(board, monkeypatch, change):
    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)
    first = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    assert first["permit_execution"] is True and first["started"] is False
    assert first["schema_version"] == 1 and first["request_uid"] == request.get_uid()
    assert first["acknowledgment_uid"] == ack_id.to_short_code()
    assert first["runtime_reference"] == "runtime-1" and first["generation"] == request.generation
    same = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    assert same["changed"] is False and same["lease_uid"] == first["lease_uid"]
    from langboard_shared.core.types import SnowflakeID

    lease_id = SnowflakeID.from_short_code(first["lease_uid"])
    with DbSession.atomic() as db:
        if change == "connection":
            connection.state = "revoked"
            db.update(connection)
        elif change == "stage":
            board[5][0].workflow_stage = "active"
            db.update(board[5][0])
        else:
            row = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
            row.expires_at = SafeDateTime.now() - timedelta(seconds=1)
            db.update(row)
    result = check_app_runtime(lease_id, runtime_token)
    assert result["state"] == "stop_requested" and result["permit_execution"] is False
    stopped = check_app_runtime(lease_id, runtime_token, stopped=True)
    assert stopped["state"] == "stopped"
    assert (
        stopped["request_uid"] == first["request_uid"] and stopped["acknowledgment_uid"] == first["acknowledgment_uid"]
    )
    assert check_app_runtime(lease_id, runtime_token)["state"] == "stopped"
    with pytest.raises(AppGovernanceDenied):
        check_app_runtime(lease_id, token_hex(32))
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        assert row.runtime_token_hash != runtime_token
        assert [h["state"] for h in row.history] == ["authorized", "stop_requested", "stopped"]


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_native_permit_and_stop_check_http(board, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard_shared.core.routing import AppRouter

    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)
    app = FastAPI()
    app.include_router(AppRouter.api)
    path = f"/apps/v1/boards/{board[2].get_uid()}/cards/{card.get_uid()}/execution-requests/{request.get_uid()}/runtime-permits"
    body = {"acknowledgment_uid": ack_id.to_short_code(), "runtime_token": runtime_token}
    with TestClient(app) as client:
        assert client.post(path, json=body).status_code == 401
        result = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"}).json()
        assert result["permit_execution"] is True and result["started"] is False
        check_path = f"/apps/v1/runtime-permits/{result['lease_uid']}/check"
        with DbSession.atomic() as db:
            connection.state = "revoked"
            db.update(connection)
        assert client.post(check_path, json={"runtime_token": runtime_token}).json()["state"] == "stop_requested"
        assert (
            client.post(check_path, json={"runtime_token": runtime_token, "stopped": True}).json()["state"] == "stopped"
        )
        assert client.post(check_path, json={"runtime_token": token_hex(32)}).status_code == 403


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_valid_heartbeat_renews_and_stopped_never_resumes(board, monkeypatch):
    from langboard_shared.core.types import SnowflakeID

    _, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)
    first = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    lease_id = SnowflakeID.from_short_code(first["lease_uid"])
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        row.expires_at = SafeDateTime.now() + timedelta(seconds=20)
        db.update(row)
    assert check_app_runtime(lease_id, runtime_token)["permit_execution"] is True
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        assert not _expired(row.expires_at, SafeDateTime.now() + timedelta(seconds=100))
    check_app_runtime(lease_id, runtime_token, stopped=True)
    with pytest.raises(AppExecutionRequestConflict):
        authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_packaged_sdk_runtime_authorize_check_stop_native_http(board, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard_sdk import AppExecution, HttpTransport

    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    from langboard_shared.core.routing import AppRouter

    app = FastAPI()
    app.include_router(AppRouter.api)
    runtime_token = token_hex(32)
    with TestClient(app) as client:

        async def transport(method, path, **kwargs):
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=transport)))
        permit = await execution.authorize_runtime(
            board[2].get_uid(),
            card.get_uid(),
            request_uid=request.get_uid(),
            acknowledgment_uid=ack_id.to_short_code(),
            runtime_token=runtime_token,
        )
        assert permit["permit_execution"] is True and permit["started"] is False
        assert (await execution.check_runtime(permit["lease_uid"], runtime_token))["permit_execution"] is True
        with DbSession.atomic() as db:
            connection.state = "revoked"
            db.update(connection)
        assert (await execution.check_runtime(permit["lease_uid"], runtime_token))["state"] == "stop_requested"
        assert (await execution.check_runtime(permit["lease_uid"], runtime_token, stopped=True))["state"] == "stopped"


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_postgres_concurrent_permit_and_stopped_replay(board, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from langboard_shared.core.types import SnowflakeID

    _, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)

    def authorize(_):
        return authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(authorize, range(4)))
    assert len({result["lease_uid"] for result in results}) == 1
    assert sum(result["changed"] for result in results) == 1
    lease_id = SnowflakeID.from_short_code(results[0]["lease_uid"])
    with DbSession.atomic() as db:
        rows = db.exec(SqlBuilder.select.table(AppExecutionLease)).all()
        assert len(rows) == 1
        rows[0].expires_at = SafeDateTime.now() - timedelta(seconds=1)
        db.update(rows[0])
    assert check_app_runtime(lease_id, runtime_token)["state"] == "stop_requested"
    with ThreadPoolExecutor(max_workers=4) as pool:
        stopped = list(pool.map(lambda _: check_app_runtime(lease_id, runtime_token, stopped=True), range(4)))
    assert all(result["state"] == "stopped" and result["permit_execution"] is False for result in stopped)
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        assert [entry["state"] for entry in row.history] == ["authorized", "stop_requested", "stopped"]


@pytest.mark.asyncio
@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
async def test_lost_permit_response_recovery_cannot_rotate_or_resurrect(board, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard_sdk import AppExecution, HttpTransport, NativeApiError
    from langboard_shared.core.routing import AppRouter

    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)
    first = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    app = FastAPI()
    app.include_router(AppRouter.api)
    with TestClient(app) as client:

        async def transport(method, path, **kwargs):
            # Recovery intentionally has no app credential: a scoped runtime token
            # must remain usable to stop after the app connection is revoked.
            return client.request(method, path, **kwargs)

        execution = AppExecution(HttpTransport(SimpleNamespace(request=transport)))
        recovered = await execution.recover_runtime(request.get_uid(), runtime_token)
        assert recovered["lease_uid"] == first["lease_uid"] and recovered["permit_execution"] is True
        assert recovered["request_uid"] == request.get_uid() and recovered["runtime_reference"] == "runtime-1"
        with pytest.raises(NativeApiError):
            await execution.recover_runtime(request.get_uid(), token_hex(32))
        with DbSession.atomic() as db:
            connection.state = "revoked"
            db.update(connection)
        assert (await execution.recover_runtime(request.get_uid(), runtime_token))["state"] == "stop_requested"
        await execution.check_runtime(first["lease_uid"], runtime_token, stopped=True)
        assert (await execution.recover_runtime(request.get_uid(), runtime_token))["state"] == "stopped"
    with DbSession.atomic() as db:
        rows = db.exec(SqlBuilder.select.table(AppExecutionLease)).all()
        assert len(rows) == 1 and rows[0].runtime_token_hash != runtime_token


@pytest.mark.parametrize("board", ["sqlite://", "postgresql-test"], indirect=True)
@pytest.mark.parametrize("gate", ["revoked", "expired", "deleted"])
def test_authorizing_credential_removal_stops_permit_despite_new_valid_credential(board, monkeypatch, gate):
    from langboard_shared.core.types import SnowflakeID
    from langboard_shared.domain.models import AppConnectionCredential
    from langboard_shared.domain.services.AppConnectionAuthentication import issue_connection_credential
    from langboard_shared.domain.services.AppExecutionLeases import recover_app_runtime

    connection, card, token, request, ack_id = permit_scope(board, monkeypatch)
    runtime_token = token_hex(32)
    permit = authorize_app_runtime(token, board[2].id, card.id, request.id, ack_id, runtime_token)
    new_token = issue_connection_credential(board[1], connection.id)["token"]
    with DbSession.atomic() as db:
        lease = db.exec(SqlBuilder.select.table(AppExecutionLease)).first()
        credential = db.exec(
            SqlBuilder.select.table(AppConnectionCredential).where(AppConnectionCredential.id == lease.credential_id)
        ).first()
        if gate == "revoked":
            credential.revoked_at = SafeDateTime.now()
            db.update(credential)
        elif gate == "expired":
            credential.expires_at = SafeDateTime.now() - timedelta(seconds=1)
            db.update(credential)
        else:
            db.delete(credential)
    with pytest.raises(AppExecutionRequestConflict):
        authorize_app_runtime(new_token, board[2].id, card.id, request.id, ack_id, runtime_token)
    recovered = recover_app_runtime(request.id, runtime_token)
    assert recovered["state"] == "stop_requested" and recovered["permit_execution"] is False
    stopped = check_app_runtime(SnowflakeID.from_short_code(permit["lease_uid"]), runtime_token, stopped=True)
    assert stopped["state"] == "stopped"


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_legacy_permit_migration_preserves_stop_reason(board, monkeypatch):
    import sqlalchemy as sa
    from langboard_shared.core.types import SnowflakeID

    connection, card, token, event = scope(board, monkeypatch)
    module = importlib.import_module("langboard.migrations.versions.20261011050000-ba4e915238c0")
    fence = importlib.import_module("langboard.migrations.versions.20261011060000-dc60b3745ae2")
    old_module_op, old_fence_op = module.op, fence.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
            db.execute(
                sa.text(
                    "INSERT INTO app_execution_lease (id,created_at,updated_at,request_id,acknowledgment_id,runtime_token_hash,state,expires_at,history) VALUES (:id,:at,:at,1,2,:hash,'authorized',:at,:history)"
                ),
                {"id": int(SnowflakeID()), "at": SafeDateTime.now().isoformat(), "hash": "a" * 64, "history": "[]"},
            )
            fence.op = module.op
            fence.upgrade()
            row = db.execute(sa.text("SELECT state,history,credential_id FROM app_execution_lease")).first()
            from json import loads

            history = loads(row.history) if isinstance(row.history, str) else row.history
            assert row.state == "stop_requested" and row.credential_id is None
            assert history[-1]["reason"] == "credential_lineage_missing"
    finally:
        module.op, fence.op = old_module_op, old_fence_op
