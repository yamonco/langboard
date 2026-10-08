"""Primary SQLite card fixtures shared by REST visibility boundary tests."""

import os
from types import SimpleNamespace
from uuid import uuid4
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    Card,
    EmployeeMembershipPolicy,
    Project,
    ProjectAssignedUser,
    ProjectRole,
    User,
)
from langboard_shared.domain.services.factory.CardService import CardService
from langboard_shared.infrastructure.repositories.factory.ProjectAssignedUserRepository import (
    ProjectAssignedUserRepository,
)
from sqlalchemy import create_engine, text


@pytest.fixture
def current_card(monkeypatch, request):
    database_url = getattr(request, "param", "sqlite://")
    if database_url == "postgresql-test":
        database_url = os.environ.get("LANGBOARD_FILE_TEST_DATABASE_URL")
        if not database_url:
            pytest.skip("Set LANGBOARD_FILE_TEST_DATABASE_URL to a disposable PostgreSQL database")
    if database_url == "sqlite-http":
        from sqlalchemy.pool import StaticPool
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(database_url)
    schema = None
    if engine.dialect.name == "postgresql":
        schema = "notification_test_" + uuid4().hex
        with engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
        with engine.begin() as db:
            for table in ("organization", "bot", "project_column"):
                db.execute(text(f'CREATE TABLE "{table}" (id BIGINT PRIMARY KEY)'))
            db.execute(text('INSERT INTO project_column (id) VALUES (0)'))
    for model in (User, Project, ProjectAssignedUser, ProjectRole, Card, EmployeeMembershipPolicy):
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
        if schema:
            with engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


