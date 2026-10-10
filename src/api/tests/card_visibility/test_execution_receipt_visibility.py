"""Execution records obey the same current card visibility as other sections."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application import execution_receipts as command
from langboard.mcp_tools import ExecutionMcp
from langboard.routes.board import ExecutionReceiptApi
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel


@pytest.mark.parametrize("surface", ["rest_read", "rest_write", "mcp_read", "native_write"])
def test_private_card_receipt_is_denied_before_storage_or_form_access(current_card, monkeypatch, surface):
    actor, project, card, service = current_card
    with DbSession.use(readonly=False) as db:
        card.owner_user_id = actor.id + 1
        card.created_by_user_id = card.owner_user_id
        db.update(card)
    close = Mock()
    monkeypatch.setattr(command, "DomainService", lambda: SimpleNamespace(card=service, close=close))
    history = Mock()
    mutation = Mock()
    monkeypatch.setattr(command, "receipt_history", history)
    monkeypatch.setattr(command, "execution_readiness_uow", mutation)
    with pytest.raises(ApiException.NotFound_404):
        if surface == "rest_read":
            ExecutionReceiptApi.get_execution_receipts(project.get_uid(), card.get_uid(), SimpleNamespace(scope={}), actor)
        elif surface == "rest_write":
            ExecutionReceiptApi.put_execution_receipt(
                project.get_uid(), card.get_uid(), 1, object(), "key", actor, request=SimpleNamespace(scope={}),
            )
        elif surface == "mcp_read":
            ExecutionMcp.get_card_execution_receipts(project.get_uid(), card.get_uid(), actor)
        else:
            command.store_execution_receipt(project.get_uid(), card.get_uid(), 1, object(), "key", actor)
    history.assert_not_called()
    mutation.assert_not_called()
    close.assert_called_once()


@pytest.mark.parametrize("channel", [CollaborationChannel.HumanUI, CollaborationChannel.Mcp])
def test_owner_read_uses_authenticated_channel_and_current_visibility(current_card, monkeypatch, channel):
    actor, project, card, service = current_card
    monkeypatch.setattr(command, "DomainService", lambda: SimpleNamespace(card=service, close=lambda: None))
    history = Mock(return_value=[{"status": "review_ready"}])
    monkeypatch.setattr(command, "receipt_history", history)
    response = ExecutionReceiptApi.get_execution_receipts(
        project.get_uid(), card.get_uid(), SimpleNamespace(scope={"collaboration_channel": channel}), actor,
    )
    assert response.body == b'{"receipts":[{"status":"review_ready"}]}'
    history.assert_called_once_with(card.id)


def test_receipt_write_revalidates_card_after_execution_lock(current_card, monkeypatch):
    actor, project, card, service = current_card
    monkeypatch.setattr(command, "DomainService", lambda: SimpleNamespace(card=service, close=lambda: None))
    current_execution = Mock()
    monkeypatch.setattr(command, "current_execution", current_execution)

    def revoke_after_lock(ids):
        assert ids == [card.id]
        with DbSession.use(readonly=False) as db:
            card.owner_user_id = actor.id + 1
            card.created_by_user_id = card.owner_user_id
            db.update(card)

    @contextmanager
    def execution():
        yield SimpleNamespace(db=object(), watch=revoke_after_lock)

    monkeypatch.setattr(command, "execution_readiness_uow", execution)
    form = command.PutExecutionReceiptForm(status="review_ready", summary="Evidence", occurred_at=datetime.now(timezone.utc))
    with pytest.raises(ApiException.NotFound_404):
        command.store_execution_receipt(
            project.get_uid(), card.get_uid(), 1, form,
            f"langboard:{project.get_uid()}:{card.get_uid()}:1:receipt", actor,
            channel=CollaborationChannel.Mcp,
        )
    current_execution.assert_not_called()
