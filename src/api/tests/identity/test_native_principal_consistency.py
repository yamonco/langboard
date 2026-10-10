"""Native authentication must not authorize from a lagging read replica."""

import os
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import DbSession  # noqa: E402
from langboard_shared.core.db.DbEngine import DbEngine  # noqa: E402
from langboard_shared.domain.models import IdentityProvider, Project, ProjectRole, User, UserIdentityLink  # noqa: E402
from langboard_shared.domain.services.factory.IdentityLinkService import IdentityLinkService  # noqa: E402
from langboard_shared.infrastructure.repositories.factory.UserIdentityLinkRepository import (  # noqa: E402
    UserIdentityLinkRepository,
)
from langboard_shared.security import RoleFinder, RoleSecurity  # noqa: E402


def test_consistent_identity_reads_primary_link_and_inactive_account(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    UserIdentityLink.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: pytest.fail("Authentication reached read replica"))
    with DbSession.atomic() as db:
        user = User(firstname="Fixture", lastname="Inactive", username="principal-test", email="fixture@example.invalid", password="fixture-only", activated_at=None)
        db.insert(user)
        db.insert(UserIdentityLink(user_id=user.id, provider=IdentityProvider.Oidc, external_id="subject", issuer="https://id.example"))
    repo = SimpleNamespace(user_identity_link=UserIdentityLinkRepository(None, None))
    service = IdentityLinkService(None, None, repo)
    try:
        found = service.get_user_by_provider_external_id(IdentityProvider.Oidc, "subject", "https://id.example", consistent=True)
        assert found is not None and found.id == user.id and found.activated_at is None
        assert service.get_user_by_provider_external_id(IdentityProvider.Oidc, "subject", "https://other.example", consistent=True) is None
    finally:
        engine.dispose()


def test_role_revocation_reads_primary_without_replica_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectRole):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: pytest.fail("Authorization reached read replica"))
    with DbSession.atomic() as db:
        user = User(firstname="Fixture", lastname="Member", username="role-test", email="role@example.invalid", password="fixture-only")
        db.insert(user)
        project = Project(owner_id=user.id, title="Role revocation fixture")
        db.insert(project)
        role = ProjectRole(user_id=user.id, project_id=project.id, actions=["read"])
        db.insert(role)
    security = RoleSecurity(ProjectRole)
    args = {"project_uid": project.get_uid()}
    try:
        assert security.is_authorized(user.id, args, ["read"], RoleFinder.project)
        with DbSession.atomic() as db:
            db.delete(role)
        assert not security.is_authorized(user.id, args, ["read"], RoleFinder.project)
    finally:
        engine.dispose()
