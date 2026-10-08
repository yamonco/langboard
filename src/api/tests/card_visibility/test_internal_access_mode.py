"""Deployment compatibility must preserve board ACLs and personal vaults."""

import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibility, CollaborationChannel
from langboard_shared.Env import Env


@pytest.mark.parametrize("mode,allowed", [("project_members", True), ("scim", False), ("invalid", False)])
def test_internal_access_requires_explicit_policy_and_current_membership(current_card, monkeypatch, mode, allowed):
    user, project, card, service = current_card
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: mode))
    _, context = service.resolve_visibility_context(project, user, CollaborationChannel.HumanUI)
    assert context.can_read_card(CardVisibility.Internal) is allowed
    assert context.can_read_card(CardVisibility.Private, owner_user_id=int(user.id))
    assert not context.can_read_card(CardVisibility.Private, owner_user_id=int(user.id) + 1)
    # An explicit compatibility mode never turns revoked accounts into readers.
    with DbSession.use(readonly=False) as db:
        user.activated_at = None
        db.update(user)
    assert service.resolve_visibility_context(project, user, CollaborationChannel.HumanUI) is None
