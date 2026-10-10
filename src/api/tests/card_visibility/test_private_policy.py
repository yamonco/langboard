"""Personal vault ownership cannot expand into collaboration or public scopes."""

from dataclasses import replace
import pytest
from langboard_shared.domain.services.CardVisibilityPolicy import (
    CardVisibility,
    CardVisibilityContext,
    CollaborationChannel,
    default_card_visibility,
)


@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_only_owner_ui_and_owner_mcp_can_read_private_even_for_internal_admin_context(channel):
    context = CardVisibilityContext(channel, True, True, True, True, actor_user_id=17)
    allowed = channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp)
    assert context.can_read_card(CardVisibility.Private, owner_user_id=17) == allowed
    for owner in (None, 18, 0, True, "17"):
        assert not context.can_read_card(CardVisibility.Private, owner_user_id=owner)
    assert not replace(context, active=False).can_read_card(CardVisibility.Private, owner_user_id=17)
    assert not replace(context, project_member=False).can_read_card(CardVisibility.Private, owner_user_id=17)
    assert replace(context, internal_member=False).can_read_card(CardVisibility.Private, owner_user_id=17) == allowed
    assert not context.can_use_card_whisper(CardVisibility.Private)


@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_private_visibility_is_immutable_and_cannot_be_promoted_even_by_owner(channel):
    context = CardVisibilityContext(channel, True, True, True, True, actor_user_id=17)
    for other in CardVisibility:
        assert not context.can_change_visibility(CardVisibility.Private, other, confirmed=True)
        assert not context.can_change_visibility(other, CardVisibility.Private, confirmed=True)


@pytest.mark.parametrize("channel", [CollaborationChannel.HumanUI, CollaborationChannel.Mcp])
def test_private_edges_are_limited_to_same_owner_private_cards(channel):
    context = CardVisibilityContext(channel, True, True, True, True, actor_user_id=17)
    assert context.can_link_cards(
        CardVisibility.Private, CardVisibility.Private, source_owner_user_id=17, target_owner_user_id=17
    )
    assert not context.can_link_cards(
        CardVisibility.Private, CardVisibility.Private, source_owner_user_id=17, target_owner_user_id=18
    )
    for other in (CardVisibility.Internal, CardVisibility.Shared):
        assert not context.can_link_cards(CardVisibility.Private, other, source_owner_user_id=17)
        assert not context.can_link_cards(other, CardVisibility.Private, target_owner_user_id=17)


def test_creation_default_uses_current_participants_and_never_reclassifies_existing_cards():
    assert default_card_visibility(17, [17]) == CardVisibility.Private
    assert default_card_visibility(17, [17, 17]) == CardVisibility.Private
    for members in (None, [], [18], [17, 18], [17, True], ["17"]):
        assert default_card_visibility(17, members) == CardVisibility.Internal
    for actor in (None, True, 0, "17"):
        assert default_card_visibility(actor, [17]) == CardVisibility.Internal
    previous = default_card_visibility(17, [17])
    assert default_card_visibility(17, [17, 18]) == CardVisibility.Internal
    assert previous == CardVisibility.Private
