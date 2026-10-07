"""PRIVATE cards never fan out into bots or their public webhook event path."""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.ai import BotDefaultTrigger
from langboard_shared.core.db import DbSession
from langboard_shared.tasks.bots.utils import BotTaskHelper as helper_class
from langboard_shared.tasks.bots.utils.BotTaskHelper import BotTaskHelper


@pytest.mark.asyncio
async def test_private_scope_stops_before_webhook_or_request(current_card, monkeypatch):
    user, project, card, _ = current_card
    module = importlib.import_module('langboard_shared.tasks.bots.utils.BotTaskHelper')
    webhook = Mock()
    request = Mock(return_value=None)
    monkeypatch.setattr(module.WebhookTask, 'webhook_task', webhook)
    monkeypatch.setattr(module, 'create_request', request)
    await BotTaskHelper.run(SimpleNamespace(), BotDefaultTrigger.BotMentioned,
        {'card_uid': card.get_uid()}, project, card)
    webhook.assert_not_called()
    request.assert_not_called()
    with DbSession.use(readonly=False) as db:
        card.visibility = 'SHARED'
        card.owner_user_id = None
        db.update(card)
    await BotTaskHelper.run(SimpleNamespace(), BotDefaultTrigger.BotMentioned,
        {'card_uid': card.get_uid()}, project, card)
    assert webhook.call_count == request.call_count == 1


def test_card_uid_cannot_override_private_scope(current_card):
    _, project, card, _ = current_card
    assert not helper_class.can_dispatch_card_scope({'card_uid': 'invalid'}, project, card)
    assert not helper_class.can_dispatch_card_scope({}, project, card)
    assert helper_class.can_dispatch_card_scope({}, project, None)


def test_checkitem_without_card_uid_still_inherits_private_parent(current_card):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import Checkitem, Checklist

    _, project, card, _ = current_card
    for model in (Checklist, Checkitem):
        model.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        checklist = Checklist(card_id=card.id, title='Private parent')
        db.insert(checklist)
        item = Checkitem(checklist_id=checklist.id, title='Private child')
        db.insert(item)
    assert not BotTaskHelper.can_dispatch_card_scope({'checkitem_uid': item.get_uid()}, project, None)
    assert not BotTaskHelper.can_dispatch_card_scope({}, project, item)
    with DbSession.use(readonly=False) as db:
        card.visibility = 'SHARED'
        card.owner_user_id = None
        db.update(card)
    assert BotTaskHelper.can_dispatch_card_scope({'checkitem_uid': item.get_uid()}, project, None)
