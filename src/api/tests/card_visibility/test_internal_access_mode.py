"""Deployment compatibility must preserve board ACLs and personal vaults."""

import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import IdentityProvider, UserIdentityLink
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibility, CollaborationChannel
from langboard_shared.Env import Env
from langboard_shared.infrastructure.repositories.factory.UserIdentityLinkRepository import UserIdentityLinkRepository


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


@pytest.mark.parametrize("issuer,subject,allowed", [
    ("https://internal.example/", "staff-1", True),
    ("https://customer.example", "customer-1", False),
    ("https://internal.example", "", False),
    (None, None, False),
])
def test_selected_identity_authority_separates_customer_without_email_inference(current_card, monkeypatch, issuer, subject, allowed):
    user, project, card, service = current_card
    UserIdentityLink.__table__.create(DbEngine.get_main_engine())
    service.repo.user_identity_link = UserIdentityLinkRepository(None, None)
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_ACCESS_MODE", property(lambda _: "oidc_issuers"))
    monkeypatch.setattr(type(Env), "CARD_INTERNAL_OIDC_ISSUERS", property(lambda _: ["https://internal.example"]))
    if issuer is not None:
        with DbSession.use(readonly=False) as db:
            db.insert(UserIdentityLink(user_id=user.id, provider=IdentityProvider.Oidc, issuer=issuer, external_id=subject))
    _, context = service.resolve_visibility_context(project, user, CollaborationChannel.HumanUI)
    assert context.can_read_card(CardVisibility.Internal) is allowed
    assert context.can_read_card(CardVisibility.Shared)
    assert not context.can_read_card(CardVisibility.Private, owner_user_id=int(user.id) + 1)
