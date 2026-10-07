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


@pytest.mark.asyncio
async def test_direct_request_and_retry_recheck_private_scope(current_card, monkeypatch):
    from langboard_shared.tasks.bots.utils.requests.BaseBotRequest import BaseBotRequest, RequestData

    _, project, card, _ = current_card
    class Request(BaseBotRequest):
        def create_request_data(self, _log) -> RequestData:
            raise AssertionError('private scope must not create payload')
    request = Request(SimpleNamespace(), 'http://example.invalid', 'test', {'card_uid': card.get_uid()}, project, card)
    log = Mock(side_effect=AssertionError('private scope must not create logs'))
    monkeypatch.setattr(request, '_create_log', log)
    module = importlib.import_module('langboard_shared.tasks.bots.utils.requests.BaseBotRequest')
    post = Mock(side_effect=AssertionError('private scope must not post'))
    monkeypatch.setattr(module, 'post', post)
    await request.execute()
    await request.request({'url': 'http://example.invalid', 'data': {}}, {}, (None, None), retried=1)
    log.assert_not_called()
    post.assert_not_called()


def test_deleted_project_blocks_current_card_scope(current_card):
    from langboard_shared.core.types import SafeDateTime

    _, project, card, _ = current_card
    with DbSession.use(readonly=False) as db:
        card.visibility = 'SHARED'
        card.owner_user_id = None
        db.update(card)
        project.deleted_at = SafeDateTime.now()
        db.update(project)
    assert not BotTaskHelper.can_dispatch_card_scope({}, project, card)


@pytest.mark.parametrize("kind", ["comment", "checklist", "checkitem"])
def test_payload_child_uid_cannot_override_current_scope(current_card, kind):
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.domain.models import Card, CardComment, Checkitem, Checklist

    _, project, private_card, _ = current_card
    for model in (CardComment, Checklist, Checkitem):
        model.__table__.create(DbEngine.get_main_engine(), checkfirst=True)
    with DbSession.use(readonly=False) as db:
        shared = Card(project_id=project.id, project_column_id=private_card.project_column_id,
                      title="Shared scope", visibility="SHARED")
        db.insert(shared)
        if kind == "comment":
            current = CardComment(card_id=shared.id)
            private = CardComment(card_id=private_card.id)
        else:
            current = Checklist(card_id=shared.id, title="Shared child")
            private = Checklist(card_id=private_card.id, title="Private child")
        db.insert(current)
        db.insert(private)
        if kind == "checkitem":
            current = Checkitem(checklist_id=current.id, title="Shared item")
            private = Checkitem(checklist_id=private.id, title="Private item")
            db.insert(current)
            db.insert(private)
    key = f"{kind}_uid"
    assert BotTaskHelper.can_dispatch_card_scope({key: current.get_uid()}, project, current)
    assert not BotTaskHelper.can_dispatch_card_scope({key: private.get_uid()}, project, current)
    assert not BotTaskHelper.can_dispatch_card_scope({key: "invalid"}, project, current)
