# ruff: noqa: F811
"""Ownership decisions preserve visibility, revisions and permanent audit receipts."""

import importlib
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import AppDefinition, Card, CardAppOwnership, CardAppOwnershipAudit
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import CardAppOwnershipConflict, set_card_app_ownership
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_app_connection_credentials import DECLARATION


def prepare(board, *, migration=False):
    engine = DbEngine.get_main_engine()
    Card.__table__.create(engine)
    if migration:
        module = importlib.import_module("langboard.migrations.versions.20261011013500-a37d248561b9")
        original = module.op
        try:
            with engine.begin() as connection:
                module.op = Operations(MigrationContext.configure(connection))
                module.upgrade()
        finally:
            module.op = original
    else:
        for model in (CardAppOwnership, CardAppOwnershipAudit):
            model.__table__.create(engine)
    with DbSession.atomic() as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
        card = Card(
            project_id=board[2].id, project_column_id=board[5][0].id, title="Independent app card", visibility="SHARED"
        )
        db.insert(card)
        for key in ("example-app", "second-app"):
            db.insert(AppDefinition(key=key, declaration={**DECLARATION, "key": key}, approved_by=board[1].id))
    return card


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_assign_transfer_release_preserve_visibility_and_audit(board):
    card = prepare(board, migration=True)
    args = board[1], board[2].id, card.id
    first = set_card_app_ownership(*args, "example-app", None)
    assert first == {"app_key": "example-app", "revision": 1, "changed": True}
    assert set_card_app_ownership(*args, "example-app", 1)["changed"] is False
    with pytest.raises(CardAppOwnershipConflict):
        set_card_app_ownership(*args, "second-app", None)
    second = set_card_app_ownership(*args, "second-app", 1)
    assert second["revision"] == 2
    with pytest.raises(CardAppOwnershipConflict):
        set_card_app_ownership(*args, None, 1)
    assert set_card_app_ownership(*args, None, 2)["revision"] == 3
    with DbSession.atomic() as db:
        current = db.exec(SqlBuilder.select.table(Card).where(Card.id == card.id)).first()
        assert current.visibility == "SHARED" and current.owner_user_id is None
        audits = db.exec(SqlBuilder.select.table(CardAppOwnershipAudit).order_by(CardAppOwnershipAudit.revision)).all()
        assert [(a.previous_app_key, a.app_key) for a in audits] == [
            (None, "example-app"),
            ("example-app", "second-app"),
            ("second-app", None),
        ]
        assert all(a.actor_id == board[1].id for a in audits)
    module = importlib.import_module("langboard.migrations.versions.20261011013500-a37d248561b9")
    original = module.op
    try:
        with DbEngine.get_main_engine().begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="ownership history"):
                module.downgrade()
    finally:
        module.op = original


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("gate", ["role", "member", "private", "foreign", "disabled", "deleted"])
def test_current_authority_and_private_visibility(board, gate):
    card = prepare(board)
    with DbSession.atomic() as db:
        if gate == "role":
            board[4].actions = ["read"]
            db.update(board[4])
        elif gate == "member":
            db.delete(board[3])
        elif gate == "private":
            card.visibility = "PRIVATE"
            card.owner_user_id = 2
            card.created_by_user_id = 2
            db.update(card)
        elif gate == "foreign":
            card.project_id = 11
            db.update(card)
        elif gate == "disabled":
            definition = db.exec(
                SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == "example-app")
            ).first()
            definition.is_enabled = False
            db.update(definition)
        else:
            from langboard_shared.core.types import SafeDateTime

            card.deleted_at = SafeDateTime.now()
            db.update(card)
    with pytest.raises(AppGovernanceDenied):
        set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(CardAppOwnershipAudit)).all()


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_release_after_disable_and_rollback_preserve_authority(board):
    card = prepare(board)
    args = board[1], board[2].id, card.id
    with pytest.raises(RuntimeError, match="abort"):
        with DbSession.atomic():
            set_card_app_ownership(*args, "example-app", None)
            raise RuntimeError("abort")
    with DbSession.atomic() as db:
        assert not db.exec(SqlBuilder.select.table(CardAppOwnership)).all()
        assert not db.exec(SqlBuilder.select.table(CardAppOwnershipAudit)).all()
    set_card_app_ownership(*args, "example-app", None)
    with DbSession.atomic() as db:
        definition = db.exec(SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == "example-app")).first()
        definition.is_enabled = False
        db.update(definition)
    assert set_card_app_ownership(*args, None, 1)["revision"] == 2
    assert set_card_app_ownership(*args, None, 2)["changed"] is False
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(CardAppOwnershipAudit)).all()) == 2
