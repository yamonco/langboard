# ruff: noqa: F811
"""App signing uses approved current targets without delivering an event."""

import hashlib
import hmac
import importlib
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.security import KeyVault
from langboard_shared.domain.models import AppEventDestination, AppExecutionOutbox, WebhookSetting
from langboard_shared.domain.services.AppEventDestination import (
    APP_EXECUTION_EVENT,
    bind_app_event_destination,
    prepare_app_event_signature,
)
from langboard_shared.domain.services.AppGovernance import AppGovernanceConflict, AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_execution_requests import accepted_request, prepare


def destination_scope(board):
    connection, definition, _, _, card, token = prepare(board)
    WebhookSetting.__table__.create(DbEngine.get_main_engine())
    module = importlib.import_module("langboard.migrations.versions.20261011034000-e71b682905fd")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as db:
            module.op = Operations(MigrationContext.configure(db))
            module.upgrade()
    finally:
        module.op = original
    accepted_request(token, board[2].id, card.id, 3)
    with DbSession.atomic() as db:
        board[1].is_admin = True
        db.update(board[1])
        definition.declaration = {
            **definition.declaration,
            "capabilities": [*definition.declaration["capabilities"], "events.receive"],
            "trust": {
                "authentication_origins": [],
                "mcp_origins": [],
                "data_origins": ["https://app.example"],
            },
        }
        db.update(definition)
        setting = WebhookSetting(
            name="App destination", url="https://app.example/events", secret_id="secret", events=[APP_EXECUTION_EVENT]
        )
        db.insert(setting)
        event = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
    return connection, definition, setting, event


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_signed_bytes_cas_and_no_delivery(board, monkeypatch):
    connection, _, setting, event = destination_scope(board)
    assert bind_app_event_destination(board[1], connection.id, setting.id, None) == {"revision": 1}
    monkeypatch.setattr(KeyVault, "get_key", lambda _: "test-signing-secret")
    result = prepare_app_event_signature(event.id, 1, timestamp=1234)
    digest = hmac.new(b"test-signing-secret", b"1234." + result["body"], hashlib.sha256).hexdigest()
    assert result["headers"]["X-Langboard-Webhook-Signature"] == f"v1={digest}"
    assert result["headers"]["X-Langboard-Webhook-Id"] == event.get_uid()
    with DbSession.atomic() as db:
        row = db.exec(SqlBuilder.select.table(AppExecutionOutbox)).first()
        assert row.state == "pending" and row.attempt_count == 0
        setting.url = "https://app.example/new-events"
        db.update(setting)
    with pytest.raises(AppGovernanceConflict):
        prepare_app_event_signature(event.id, 1)
    assert bind_app_event_destination(board[1], connection.id, setting.id, 1) == {"revision": 2}
    with pytest.raises(AppGovernanceConflict):
        prepare_app_event_signature(event.id, 1)
    # A pending event cannot silently migrate to the newly approved destination.
    with pytest.raises(AppGovernanceConflict):
        prepare_app_event_signature(event.id, 2)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("gate", ["http", "origin", "event", "secret", "admin", "revoked", "trust"])
def test_invalid_or_changed_destination_never_signs(board, monkeypatch, gate):
    connection, definition, setting, event = destination_scope(board)
    if gate in ("revoked", "trust"):
        bind_app_event_destination(board[1], connection.id, setting.id, None)
    with DbSession.atomic() as db:
        if gate == "http":
            setting.url = "http://app.example/events"
        elif gate == "origin":
            setting.url = "https://unapproved.example/events"
        elif gate == "event":
            setting.events = None
        elif gate == "secret":
            setting.secret_id = None
        elif gate == "admin":
            board[1].is_admin = False
            db.update(board[1])
        elif gate == "revoked":
            connection.state = "revoked"
            db.update(connection)
        else:
            definition.declaration = {**definition.declaration, "publisher": "Changed publisher"}
            db.update(definition)
        db.update(setting)
    monkeypatch.setattr(KeyVault, "get_key", lambda _: pytest.fail("Invalid target must not load secrets"))
    with pytest.raises((AppGovernanceDenied, AppGovernanceConflict)):
        if gate in ("revoked", "trust"):
            prepare_app_event_signature(event.id, 1)
        else:
            bind_app_event_destination(board[1], connection.id, setting.id, None)
    if gate not in ("revoked", "trust"):
        with DbSession.atomic() as db:
            assert not db.exec(SqlBuilder.select.table(AppEventDestination)).all()


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_missing_vault_secret_denies_unsigned_event(board, monkeypatch):
    connection, _, setting, event = destination_scope(board)
    bind_app_event_destination(board[1], connection.id, setting.id, None)
    monkeypatch.setattr(KeyVault, "get_key", lambda _: None)
    with pytest.raises(AppGovernanceDenied):
        prepare_app_event_signature(event.id, 1)
