# ruff: noqa: F811
"""Owner-app metadata cannot authorize bots to mutate exclusive cards."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import Bot, CardAppOwnership, CardAppOwnershipAudit
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.CardAppGovernance import set_card_app_ownership
from langboard_shared.domain.services.CardAppMutation import guard_card_app_mutation
from langboard_shared.domain.services.factory.CardCommentService import CardCommentService
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.domain.services.factory.CheckitemService import CheckitemService
from langboard_shared.domain.services.factory.ChecklistService import ChecklistService
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from test_card_app_ownership import prepare


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize("operation", ["card", "stage", "checklist", "checkitem", "comment"])
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
    }
    with pytest.raises(AppGovernanceDenied):
        operations[operation]()
    assert card.title == "Independent app card" and card.project_column_id == board[5][0].id


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
