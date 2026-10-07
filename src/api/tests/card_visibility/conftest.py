"""Primary SQLite card fixtures shared by REST visibility boundary tests."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Card, Project, ProjectAssignedUser, ProjectRole, User
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)
from sqlalchemy import create_engine


@pytest.fixture
def current_card(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectAssignedUser, ProjectRole, Card):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        user = User(firstname="Fixture", lastname="Actor", email="actor@example.invalid",
                    password="test-only", activated_at=SafeDateTime.now())
        db.insert(user)
        project = Project(owner_id=user.id, title="Current visibility")
        db.insert(project)
        card = Card(project_id=project.id, title="Private fixture", visibility="PRIVATE", owner_user_id=user.id, created_by_user_id=user.id)
        db.insert(card)
    scim = SimpleNamespace(is_employee=lambda _: False)
    card_service = CardService(lambda _: scim, lambda _: None,
                               SimpleNamespace(project_assigned_user=ProjectAssignedUserRepository(None, None)))
    try:
        yield user, project, card, card_service
    finally:
        engine.dispose()


