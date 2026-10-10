# ruff: noqa: F811
"""Real PostgreSQL request transactions serialize accepted identities and stale selections."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import AppExecutionOutbox, AppExecutionRequest, Card
from langboard_shared.domain.services.AppExecutionGrant import evaluate_current_execution_grant
from langboard_shared.domain.services.AppExecutionRequests import AppExecutionRequestConflict, request_app_execution
from langboard_shared.domain.services.CardAppResources import set_card_app_resources
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from sqlalchemy import text
from test_app_execution_requests import prepare


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_concurrent_duplicate_acceptance_records_one_request_and_event(board):
    _, _, _, _, card, token = prepare(board)
    version = evaluate_current_execution_grant(token, board[2].id, card.id, 3)["authority_version"]

    def accept(_):
        return request_app_execution(token, board[2].id, card.id, 3, expected_authority_version=version)

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(accept, range(4)))
    assert len({r["request_uid"] for r in receipts}) == 1
    assert sum(r["changed"] for r in receipts) == 1
    assert all(r["started"] is False and r["authority"]["authority_version"] == version for r in receipts)
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()) == 1
        assert len(db.exec(SqlBuilder.select.table(AppExecutionOutbox)).all()) == 1


@pytest.mark.parametrize("board", ["postgresql-test"], indirect=True)
def test_request_waits_for_card_lock_then_rejects_committed_selection_change(board):
    connection, _, _, resources, card, token = prepare(board)
    version = evaluate_current_execution_grant(token, board[2].id, card.id, 3)["authority_version"]
    locked, release = Event(), Event()

    def change_selection():
        with DbSession.atomic() as db:
            db.exec(SqlBuilder.select.table(Card).where(Card.id == card.id).with_for_update()).first()
            set_card_app_resources(board[1], board[2].id, card.id, connection.id, [resources[1].get_uid()], 1)
            locked.set()
            assert release.wait(20), "Test did not release selection transaction"

    def accept():
        return request_app_execution(token, board[2].id, card.id, 3, expected_authority_version=version)

    engine = DbEngine.get_main_engine()
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(change_selection)
        assert locked.wait(10)
        request = pool.submit(accept)
        try:
            # Observe the actual waiter rather than assuming overlap from a sleep.
            import time

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with engine.connect() as db:
                    waiting = db.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid()"
                        )
                    ).scalar_one()
                if waiting:
                    break
                if request.done():
                    pytest.fail("Request bypassed the transaction's card lock")
                time.sleep(0.02)
            else:
                pytest.fail("No PostgreSQL lock waiter observed")
        finally:
            release.set()
        writer.result(timeout=10)
        with pytest.raises(AppExecutionRequestConflict):
            request.result(timeout=10)
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(AppExecutionRequest)).all()
        assert not db.exec(SqlBuilder.select.table(AppExecutionOutbox)).all()
