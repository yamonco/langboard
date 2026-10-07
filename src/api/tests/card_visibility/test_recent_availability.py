"""Recent-card restoration must not disclose a vault or revoked membership."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Card, Project, ProjectAssignedUser, ProjectColumn, User
from langboard_shared.domain.services.CardVisibilityPolicy import CollaborationChannel
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)
from sqlalchemy import create_engine


def test_recent_cards_revalidate_actor_and_filter_visibility_before_return(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, ProjectAssignedUser, Card):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    try:
        with DbSession.use(readonly=False) as db:
            users = [User(firstname="Fixture", lastname=str(i), email=f"u{i}@example.invalid",
                          password="test-only", activated_at=SafeDateTime.now()) for i in range(2)]
            for user in users:
                db.insert(user)
            owner, member = users
            project = Project(owner_id=owner.id, title="Scoped recent fixture")
            db.insert(project)
            column = ProjectColumn(project_id=project.id, name="Work")
            db.insert(column)
            assignment = ProjectAssignedUser(project_id=project.id, user_id=member.id)
            db.insert(assignment)
            cards = [Card(project_id=project.id, project_column_id=column.id, title=visibility,
                          visibility=visibility, owner_user_id=vault_owner,
                          created_by_user_id=vault_owner) for visibility, vault_owner in (
                              ("SHARED", None), ("INTERNAL", None),
                              ("PRIVATE", member.id), ("PRIVATE", owner.id))]
            for card in cards:
                db.insert(card)
        repository = SimpleNamespace(
            card=CardRepository(lambda _: None, lambda _: None),
            project_assigned_user=ProjectAssignedUserRepository(lambda _: None, lambda _: None),
        )
        scim = SimpleNamespace(is_employee=lambda user: False)
        service = CardService(lambda _: scim, lambda _: None, repository)
        uids = [card.get_uid() for card in cards]
        for channel in CollaborationChannel:
            expected = {uids[0], uids[2]} if channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp) else {uids[0]}
            assert set(service.get_existing_uids(project, uids, user=member, channel=channel)) == expected
        scim.is_employee = lambda user: True
        assert set(service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp)) == set(uids[:3])
        scim.is_employee = lambda user: None
        assert service.get_existing_uids(project, uids, user=member) == [uids[0]]
        # The auth User remains active in memory after primary DB revocation.
        with DbSession.use(readonly=False) as db:
            inactive = member.model_copy(deep=True)
            inactive.activated_at = None
            db.update(inactive)
        assert member.activated_at is not None
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp) == []
        with DbSession.use(readonly=False) as db:
            inactive.activated_at = member.activated_at
            db.update(inactive)
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp)
        with DbSession.use(readonly=False) as db:
            db.delete(assignment)
        assert service.get_existing_uids(project, uids, user=member, channel=CollaborationChannel.Mcp) == []
        assert set(service.get_existing_uids(project, uids, user=owner, channel=CollaborationChannel.HumanUI)) == {uids[0], uids[3]}
        with DbSession.use(readonly=False) as db:
            removed_project = project.model_copy(deep=True)
            removed_project.deleted_at = SafeDateTime.now()
            db.update(removed_project)
        assert project.deleted_at is None
        assert service.get_existing_uids(project, uids, user=owner, channel=CollaborationChannel.HumanUI) == []
        assert service.get_existing_uids(project, [], user=owner) == []
        with pytest.raises(ValueError, match="200"):
            service.get_existing_uids(project, [uids[0]] * 201, user=owner)
    finally:
        engine.dispose()
