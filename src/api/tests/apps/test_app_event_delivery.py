# ruff: noqa: F811
"""Durable claims fence revoked grants, stale workers and bounded delivery retries."""

from datetime import timedelta
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.security import KeyVault
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import AppExecutionOutbox
from langboard_shared.domain.services.AppEventDelivery import claim_app_event, finish_app_event
from langboard_shared.domain.services.AppEventDestination import bind_app_event_destination
from langboard_shared.domain.services.AppGovernance import AppGovernanceConflict
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_event_destination import destination_scope


def delivery_scope(board, monkeypatch):
    connection, _, setting, event = destination_scope(board)
    bind_app_event_destination(board[1], connection.id, setting.id, None)
    monkeypatch.setattr(KeyVault, "get_key", lambda _: "test-signing-secret")
    return connection, setting, event


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_claim_exclusion_crash_recovery_and_stale_finish(board, monkeypatch):
    _, _, event = delivery_scope(board, monkeypatch)
    first = claim_app_event(event.id, 1)
    assert first["attempt_count"] == 1
    assert claim_app_event(event.id, 1) is None
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.payload["destination"]["revision"] == 1
        row.lease_until = SafeDateTime.now() - timedelta(seconds=1)
        db.update(row)
    second = claim_app_event(event.id, 1)
    assert second["attempt_count"] == 2 and second["claim_token"] != first["claim_token"]
    with pytest.raises(AppGovernanceConflict):
        finish_app_event(event.id, first["claim_token"], delivered=True)
    result = finish_app_event(event.id, second["claim_token"], delivered=True)
    assert result["state"] == "delivered" and result["started"] is False
    assert claim_app_event(event.id, 1) is None
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert [entry["outcome"] for entry in row.delivery_history] == [
            "claimed",
            "lease_expired",
            "claimed",
            "delivered",
        ]


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_failures_have_bounded_retry_identity(board, monkeypatch):
    _, _, event = delivery_scope(board, monkeypatch)
    bodies = []
    for attempt in range(1, 5):
        claim = claim_app_event(event.id, 1)
        assert claim["event_uid"] == event.get_uid() and claim["attempt_count"] == attempt
        bodies.append(claim["body"])
        result = finish_app_event(event.id, claim["claim_token"], delivered=False)
        assert result["state"] == ("failed" if attempt == 4 else "pending")
    assert len(set(bodies)) == 1
    assert claim_app_event(event.id, 1) is None

    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert len(row.delivery_history) == 8


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("change", ["connection", "stage", "destination", "payload"])
def test_current_fence_blocks_pending_without_attempt(board, monkeypatch, change):
    connection, setting, event = delivery_scope(board, monkeypatch)
    with DbSession.atomic() as db:
        if change == "connection":
            connection.state = "revoked"
            db.update(connection)
        elif change == "stage":
            board[5][0].workflow_stage = "active"
            db.update(board[5][0])
        elif change == "payload":
            row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
            row.payload = {**row.payload, "resource_uids": []}
            db.update(row)
        else:
            setting.url = "https://app.example/changed"
            db.update(setting)
    assert claim_app_event(event.id, 1) is None
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == "blocked" and row.attempt_count == 0
        assert row.claim_token is None


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_postgres_concurrent_claim_has_one_lease(board, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _, _, event = delivery_scope(board, monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: claim_app_event(event.id, 1), range(4)))
    claims = [result for result in results if result is not None]
    assert len(claims) == 1 and claims[0]["attempt_count"] == 1
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == "delivering" and len(row.delivery_history) == 1
