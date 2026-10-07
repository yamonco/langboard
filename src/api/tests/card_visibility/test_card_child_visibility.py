"""Child APIs inherit card visibility before storage, lookups and commands."""

import inspect
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board import (
    BoardCardAttachmentApi,
    BoardCardCheckitemApi,
    BoardCardChecklistApi,
    BoardCardCommentApi,
)
from langboard.routes.board.CardAccess import require_card_child
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.storage import FileModel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import CardAttachment, CardComment, Checkitem, Checklist


MODULES = (BoardCardCommentApi, BoardCardChecklistApi, BoardCardCheckitemApi, BoardCardAttachmentApi)
ROUTES = tuple((module, name) for module in MODULES for name, callback in vars(module).items()
               if inspect.isfunction(callback) and callback.__module__ == module.__name__)


def invoke(module, name, project, card, user, service, channel):
    callback = getattr(module, name)
    kwargs = dict(project_uid=project.get_uid(), card_uid=card.get_uid(),
                  request=SimpleNamespace(scope={"collaboration_channel": channel}), service=service)
    for param in inspect.signature(callback).parameters:
        if param in ("user", "user_or_bot"):
            kwargs[param] = user
        elif param.endswith("_uid") and param not in kwargs:
            kwargs[param] = "sentinel-child"
        elif param in ("form", "comment", "attachment"):
            kwargs[param] = object()
    return callback(**kwargs)


@pytest.mark.parametrize("module,name", ROUTES, ids=[name for _, name in ROUTES])
@pytest.mark.parametrize("denial", ("api_private", "foreign_private", "internal_external", "inactive"))
def test_child_route_denies_before_touching_storage_form_or_child(current_card, monkeypatch, module, name, denial):
    user, project, card, card_service = current_card
    channel = CollaborationChannel.HumanUI
    with DbSession.use(readonly=False) as db:
        if denial == "api_private":
            channel = CollaborationChannel.Api
        elif denial == "foreign_private":
            card.owner_user_id = user.id + 1
            card.created_by_user_id = card.owner_user_id
            db.update(card)
        elif denial == "internal_external":
            card.visibility, card.owner_user_id = "INTERNAL", None
            db.update(card)
        elif denial == "inactive":
            user.activated_at = None
            db.update(user)
    commands = Mock()
    commands.resolve_readable_card = card_service.resolve_readable_card
    service = SimpleNamespace(card=commands, card_comment=Mock(), checklist=Mock(), checkitem=Mock(), card_attachment=Mock())
    upload = Mock()
    monkeypatch.setattr(BoardCardAttachmentApi.Storage, "upload", upload)
    with pytest.raises(ApiException.NotFound_404):
        invoke(module, name, project, card, user, service, channel)
    assert commands.mock_calls == []
    for target in (service.card_comment, service.checklist, service.checkitem, service.card_attachment, upload):
        assert target.mock_calls == []


@pytest.mark.parametrize("model", (CardComment, Checklist, Checkitem, CardAttachment))
def test_primary_child_provenance_rejects_foreign_and_deleted_rows(current_card, model):
    user, _, card, _ = current_card
    engine = DbEngine.get_main_engine()
    for table in (CardComment, Checklist, Checkitem, CardAttachment):
        table.__table__.create(engine)
    with DbSession.use(readonly=False) as db:
        checklist = Checklist(card_id=card.id, title="Child checklist")
        db.insert(checklist)
        if model is CardComment:
            child = CardComment(card_id=card.id, user_id=user.id)
        elif model is Checklist:
            child = checklist
        elif model is Checkitem:
            child = Checkitem(checklist_id=checklist.id, title="Task")
        else:
            child = CardAttachment(card_id=card.id, user_id=user.id, filename="fixture.pdf",
                file=FileModel(storage_type="test", storage_name="test", path="/tmp/fixture", filename="fixture.pdf", original_filename="fixture.pdf"))
        if child is not checklist:
            db.insert(child)
    require_card_child(card, model, child.get_uid())
    with DbSession.use(readonly=False) as db:
        owner = checklist if model is Checkitem else child
        owner.card_id = card.id + 1
        db.update(owner)
    with pytest.raises(ApiException.NotFound_404):
        require_card_child(card, model, child.get_uid())
    with DbSession.use(readonly=False) as db:
        owner.card_id = card.id
        owner.deleted_at = SafeDateTime.now()
        db.update(owner)
    with pytest.raises(ApiException.NotFound_404):
        require_card_child(card, model, child.get_uid())


@pytest.mark.parametrize("module,name", [(m, n) for m, n in ROUTES if any(
    p in inspect.signature(getattr(m, n)).parameters for p in ("comment_uid", "attachment_uid", "checkitem_uid", "checklist_uid"))])
def test_foreign_child_rejected_before_ownership_check(current_card, module, name, monkeypatch):
    user, project, card, card_service = current_card
    def reject(*_):
        raise ApiException.NotFound_404()
    gate = Mock(side_effect=reject)
    monkeypatch.setattr(module, "require_card_child", gate)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=card_service.resolve_readable_card),
                              card_comment=Mock(), checklist=Mock(), checkitem=Mock(), card_attachment=Mock())
    with pytest.raises(ApiException.NotFound_404):
        invoke(module, name, project, card, user, service, CollaborationChannel.Mcp)
    gate.assert_called_once()
    for target in (service.card_comment, service.checklist, service.checkitem, service.card_attachment):
        assert target.mock_calls == []


@pytest.mark.parametrize("channel", (CollaborationChannel.HumanUI, CollaborationChannel.Mcp))
def test_private_owner_reads_own_comment_and_checklists(current_card, channel):
    user, project, card, card_service = current_card
    CardComment.__table__.create(DbEngine.get_main_engine())
    with DbSession.use(readonly=False) as db:
        comment = CardComment(card_id=card.id, user_id=user.id)
        db.insert(comment)
    reader = Mock(return_value={"uid": comment.get_uid()})
    checklist_reader = Mock(return_value=[])
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=card_service.resolve_readable_card),
                              card_comment=SimpleNamespace(get_as_api=reader),
                              checklist=SimpleNamespace(get_api_list_by_card=checklist_reader))
    request = SimpleNamespace(scope={"collaboration_channel": channel})
    BoardCardCommentApi.get_card_comment(project.get_uid(), card.get_uid(), request, comment.get_uid(), user, service)
    reader.assert_called_once_with(card.get_uid(), comment.get_uid())
    BoardCardChecklistApi.get_card_checklists(project.get_uid(), card.get_uid(), request, user, service)
    checklist_reader.assert_called_once_with(card.get_uid())
