"""Direct card actions must gate current visibility before invoking a command."""

import inspect
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board import BoardCardApi
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ProjectAssignedUser, ProjectRole


ACTIONS = (
    "change_card_details", "update_card_assigned_users", "add_card_assignee",
    "change_card_order_or_move_column", "update_card_labels",
    "update_card_relationships", "patch_card_relationships", "set_card_completed",
    "cardify_selection", "convert_card_checkboxes", "get_card_comment_counts",
    "copy_selection_to_wiki", "archive_card", "delete_card", "replace_card_content_blocks",
)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("denial", ("api_private", "bot_channel", "foreign_private", "internal_external", "inactive", "deleted"))
def test_denied_card_action_never_accesses_form_or_dispatches_command(current_card, action, denial):
    user, project, card, card_service = current_card
    channel = CollaborationChannel.HumanUI
    with DbSession.use(readonly=False) as db:
        if denial == "api_private":
            channel = CollaborationChannel.Api
        elif denial == "bot_channel":
            channel = CollaborationChannel.Bot
        elif denial == "foreign_private":
            card.owner_user_id = user.id + 1
            card.created_by_user_id = card.owner_user_id
            db.update(card)
        elif denial == "internal_external":
            card.visibility = "INTERNAL"
            card.owner_user_id = None
            db.update(card)
        elif denial == "inactive":
            user.activated_at = None
            db.update(user)
        elif denial == "deleted":
            card.deleted_at = SafeDateTime.now()
            db.update(card)
    # All command targets are sentinels: denial must happen before any access.
    commands = Mock()
    commands.resolve_readable_card = card_service.resolve_readable_card
    service = SimpleNamespace(card=commands, card_relationship=Mock(), card_content_block=Mock(), project=Mock())
    callback = getattr(BoardCardApi, action)
    kwargs = dict(project_uid=project.get_uid(), card_uid=card.get_uid(),
                  request=SimpleNamespace(scope={"collaboration_channel": channel}), user_or_bot=user, service=service)
    if "form" in inspect.signature(callback).parameters:
        kwargs["form"] = object()
    if action == "add_card_assignee":
        kwargs["assignee_uid"] = "member"
    with pytest.raises(ApiException.NotFound_404):
        callback(**kwargs)
    assert commands.mock_calls == []
    for target in (service.card_relationship, service.card_content_block, service.project):
        assert target.mock_calls == []


@pytest.mark.parametrize("channel", (None, CollaborationChannel.HumanUI, CollaborationChannel.Mcp))
def test_allowed_action_uses_server_channel_and_preserves_existing_command(channel):
    actor = object()
    resolver = Mock(return_value=(object(), object(), object()))
    command = Mock(return_value=True)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=resolver, update_labels=command))
    request = SimpleNamespace(scope={} if channel is None else {"collaboration_channel": channel})
    form = SimpleNamespace(labels=["existing-local-label"])
    BoardCardApi.update_card_labels("p", "c", request, form, actor, service)
    resolver.assert_called_once_with("p", "c", actor, channel or CollaborationChannel.Api)
    command.assert_called_once_with(actor, "p", "c", form.labels)


@pytest.mark.parametrize("channel", (CollaborationChannel.HumanUI, CollaborationChannel.Mcp))
def test_private_owner_can_change_labels_through_supported_channel(current_card, channel):
    user, project, card, card_service = current_card
    command = Mock(return_value=True)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=card_service.resolve_readable_card, update_labels=command))
    BoardCardApi.update_card_labels(project.get_uid(), card.get_uid(), SimpleNamespace(scope={"collaboration_channel": channel}),
                                   SimpleNamespace(labels=[]), user, service)
    command.assert_called_once()


def test_cached_actor_membership_revocation_denies_mutation(current_card):
    user, project, card, card_service = current_card
    with DbSession.use(readonly=False) as db:
        project.owner_id = user.id + 1
        db.update(project)
        membership = ProjectAssignedUser(project_id=project.id, user_id=user.id)
        db.insert(membership)
        db.insert(ProjectRole(project_id=project.id, user_id=user.id, actions=["read", "card_update"]))
    assert card_service.resolve_readable_card(project, card, user, CollaborationChannel.Mcp) is not None
    with DbSession.use(readonly=False) as db:
        db.delete(membership)
    command = Mock(return_value=True)
    service = SimpleNamespace(card=SimpleNamespace(resolve_readable_card=card_service.resolve_readable_card, update_labels=command))
    with pytest.raises(ApiException.NotFound_404):
        BoardCardApi.update_card_labels(project.get_uid(), card.get_uid(), SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.Mcp}),
                                       SimpleNamespace(labels=[]), user, service)
    command.assert_not_called()
