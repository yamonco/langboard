import os
from dataclasses import replace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.services.CardVisibilityPolicy import (  # noqa: E402
    DEFAULT_CARD_VISIBILITY,
    CardVisibility,
    CardVisibilityContext,
    CollaborationChannel,
)


def test_unknown_external_removed_or_inactive_members_cannot_read_internal():
    context = CardVisibilityContext(CollaborationChannel.HumanUI, True, True, True, True)
    assert DEFAULT_CARD_VISIBILITY == CardVisibility.Internal
    assert context.can_read_card(CardVisibility.Internal)
    for denied in (
        replace(context, internal_member=None),
        replace(context, internal_member=False),
        replace(context, project_member=False),
        replace(context, active=False),
        replace(context, internal_member="true"),
    ):
        assert not denied.can_read_card(CardVisibility.Internal)
        assert not denied.can_use_whisper
        assert not denied.can_change_visibility(CardVisibility.Internal, CardVisibility.Shared, confirmed=True)
    external = replace(context, internal_member=False)
    assert external.can_read_card(CardVisibility.Shared)
    assert not replace(external, project_member=False).can_read_card(CardVisibility.Shared)
    assert not context.can_read_card("UNKNOWN")


@pytest.mark.parametrize("channel", list(CollaborationChannel))
def test_only_confirmed_human_ui_can_share_and_only_humans_can_use_whisper(channel):
    context = CardVisibilityContext(channel, True, True, True, True)
    # MCP may act as a linked human account, but its transport remains MCP.
    assert context.can_read_card(CardVisibility.Internal)
    assert context.can_use_whisper == (channel == CollaborationChannel.HumanUI)
    assert context.can_change_visibility(CardVisibility.Internal, CardVisibility.Shared, confirmed=True) == (
        channel == CollaborationChannel.HumanUI
    )
    assert not context.can_change_visibility(CardVisibility.Internal, CardVisibility.Shared)
    assert not replace(context, can_update_card=False).can_change_visibility(
        CardVisibility.Internal, CardVisibility.Shared, confirmed=True
    )
    assert context.can_change_visibility(CardVisibility.Shared, CardVisibility.Internal)
    assert not context.can_change_visibility(CardVisibility.Internal, "UNKNOWN", confirmed=True)


def test_unactivated_visibility_and_audit_do_not_leak_into_generic_payloads():
    from langboard_shared.domain.models import Card, CardVisibilityChange

    card = Card(project_id=1, project_column_id=2, title="Private")
    assert card.visibility == "INTERNAL"
    assert "visibility" not in card.api_response()
    audit = CardVisibilityChange(
        card_id=card.id, changed_by_user_id=3, channel="human_ui", previous_visibility="INTERNAL", next_visibility="SHARED"
    )
    assert audit.notification_data() == {}
    response = audit.api_response()
    assert not {"card_id", "changed_by_user_id", "previous_visibility", "next_visibility"}.intersection(response)
