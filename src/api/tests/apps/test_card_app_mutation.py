# ruff: noqa: F811
"""Owner-app metadata cannot authorize bots to mutate exclusive cards."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application import execution_receipts as receipts
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.routing import ApiException
from langboard_shared.domain.models import Bot, CardAppOwnership, CardAppOwnershipAudit
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import set_card_app_ownership
from langboard_shared.domain.services.CardAppMutation import guard_card_app_mutation
from langboard_shared.domain.services.factory.CardAttachmentService import CardAttachmentService
from langboard_shared.domain.services.factory.CardCommentService import CardCommentService
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_card_app_ownership import prepare


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("operation", ["card", "stage", "checklist", "checkitem", "comment", "upload", "rename", "delete_file", "file_order", "processing", "embedding"])
def test_native_services_deny_bot_before_mutation(board, operation):
    card = prepare(board)
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    actor = Bot(
        name="Automation",
        bot_uname="bot-test",
        app_api_token="test-only",
        platform="default",
        platform_running_type="default",
    )
    # A payload claiming the right app is not an authenticated app connection.
    actor.__dict__["app_key"] = "example-app"
    operations = {
        "card": lambda: CardService(None, None, None).update(actor, board[2], card, {"title": "Changed"}),
        "stage": lambda: CardService(None, None, None).change_order(actor, board[2], card, 0, board[5][1]),
        "checklist": lambda: ChecklistService(None, None, None).create(actor, board[2], card, "Changed"),
        "checkitem": lambda: CheckitemService(None, None, None).create(actor, board[2], card, None, "Changed"),
        "comment": lambda: CardCommentService(None, None, None).create(actor, board[2], card, {}),
        "upload": lambda: CardAttachmentService(None, None, None).create(actor, board[2], card, None),
        "rename": lambda: CardAttachmentService(None, None, None).change_name(actor, board[2], card, None, "Changed"),
        "delete_file": lambda: CardAttachmentService(None, None, None).delete(actor, board[2], card, None),
        "file_order": lambda: CardAttachmentService(None, None, None).change_order(board[2], card, None, 0, user=actor),
        "processing": lambda: CardAttachmentService(None, None, None).request_document_processing(board[2], card, None, user=actor),
        "embedding": lambda: CardAttachmentService(None, None, None).request_document_embedding(board[2], card, None, user=actor),
    }
    with pytest.raises(AppGovernanceDenied):
        operations[operation]()
    assert card.title == "Independent app card" and card.project_column_id == board[5][0].id


@pytest.mark.parametrize("operation", ["change_order", "request_document_processing", "request_document_embedding"])
def test_attachment_writer_requires_actor_before_repository_access(operation):
    service = CardAttachmentService(None, None, None)
    args = ("project", "card", "attachment", 0) if operation == "change_order" else ("project", "card", "attachment")
    with pytest.raises(TypeError, match="user"):
        getattr(service, operation)(*args)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("assign_after_lock", [False, True])
def test_receipt_owner_fence_precedes_persistence_and_review(board, monkeypatch, assign_after_lock):
    card = prepare(board)
    actor = Bot(name="Automation", bot_uname="bot-test", app_api_token="test-only",
                platform="default", platform_running_type="default")
    actor.__dict__["app_key"] = "example-app"
    if not assign_after_lock:
        set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    # Isolate the write fence even when a caller has already passed read authority.
    readable = Mock(return_value=(board[2], card))
    monkeypatch.setattr(receipts, "require_receipt_card", readable)
    generation = Mock()
    checklist = Mock()
    review = Mock()
    monkeypatch.setattr(receipts, "current_execution", generation)
    monkeypatch.setattr(receipts, "_reconcile_machine_checklist", checklist)
    monkeypatch.setattr(receipts, "_move_to_review", review)

    def watch(ids):
        assert ids == [card.id]
        if assign_after_lock:
            set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)

    @contextmanager
    def execution():
        with DbSession.atomic() as db:
            yield SimpleNamespace(db=db, watch=watch)

    monkeypatch.setattr(receipts, "execution_readiness_uow", execution)
    form = receipts.PutExecutionReceiptForm(status="review_ready", summary="Evidence",
                                           occurred_at=datetime.now(timezone.utc))
    with pytest.raises(ApiException.Forbidden_403):
        receipts.store_execution_receipt(board[2].get_uid(), card.get_uid(), 1, form,
            f"langboard:{board[2].get_uid()}:{card.get_uid()}:1:receipt", actor)
    assert readable.call_count == (2 if assign_after_lock else 1)
    generation.assert_not_called()
    checklist.assert_not_called()
    review.assert_not_called()


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_release_and_human_permission_paths_do_not_infer_app_grants(board):
    card = prepare(board)
    actor = Bot(
        name="Automation",
        bot_uname="bot-test",
        app_api_token="test-only",
        platform="default",
        platform_running_type="default",
    )
    calls = []

    @guard_card_app_mutation
    def mutation(user_or_bot, project, card):
        calls.append(user_or_bot)
        return "existing permission path"

    assert mutation(actor, board[2], card) == "existing permission path"
    set_card_app_ownership(board[1], board[2].id, card.id, "example-app", None)
    # User calls still reach the native operation's own permissions.
    assert mutation(board[1], board[2], card) == "existing permission path"
    with pytest.raises(AppGovernanceDenied):
        mutation(SimpleNamespace(app_key="example-app"), board[2], card)
    with pytest.raises(AppGovernanceDenied):
        mutation(actor, board[2], card)
    set_card_app_ownership(board[1], board[2].id, card.id, None, 1)
    assert mutation(actor, board[2], card) == "existing permission path"
    with DbSession.atomic() as db:
        assert len(db.exec(SqlBuilder.select.table(CardAppOwnershipAudit)).all()) == 2
        assert db.exec(SqlBuilder.select.table(CardAppOwnership)).first().app_key is None
