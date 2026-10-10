"""Native SQLite policy persistence, authority and ownership acceptance."""

import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import (
    AppConnection,
    AppGovernancePolicy,
    Organization,
    Project,
    ProjectAssignedUser,
    User,
)
from langboard_shared.domain.services.AppGovernance import (
    AppGovernanceConflict,
    AppGovernanceDenied,
    current_policy,
    get_policy,
    list_managed_organizations,
    require_app_allowed,
    require_connection_access,
    save_policy,
)
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def governance(monkeypatch, tmp_path):
    from langboard_shared.Env import Env
    monkeypatch.setattr(type(Env), "CACHE_DIR", property(lambda _: tmp_path / "cache"))
    from langboard_shared.publishers import AppSettingPublisher
    monkeypatch.setattr(AppSettingPublisher, "apps_changed", lambda: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, Organization, Project, ProjectAssignedUser, AppConnection, AppGovernancePolicy):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with Session(engine, expire_on_commit=False) as db:
        users = [
            User(
                id=i,
                firstname="Policy",
                lastname="Actor",
                email=f"u{i}@example.invalid",
                password="test",
                activated_at=SafeDateTime.now(),
                is_admin=i == 1,
            )
            for i in (1, 2, 3)
        ]
        org = Organization(id=10, name="Org", slug="org", owner_user_id=2)
        other = Organization(id=11, name="Other", slug="other", owner_user_id=3)
        project = Project(id=20, owner_id=2, organization_id=10, title="Board")
        personal = AppConnection(id=30, app_key="example", owner_id=2, state="connected")
        shared = AppConnection(
            id=31, app_key="example", owner_id=2, state="connected", ownership="organization", organization_id=10
        )
        db.add_all([*users, org, other, project, personal, shared])
        db.commit()
    yield engine, users, org, project, personal, shared
    engine.dispose()


def test_policy_precedence_revision_and_inheritance(governance):
    _, (admin, owner, _), org, *_ = governance
    default = get_policy(admin)
    assert default["mode"] == default["effective_mode"] == "approved_only"
    assert get_policy(admin) == default
    unset = get_policy(owner, org.id)
    assert unset["mode"] is None and unset["effective_mode"] == "approved_only"
    relaxed = save_policy(owner, "personal_allowed", unset["revision"], org.id)
    assert relaxed["effective_mode"] == "approved_only"
    with pytest.raises(AppGovernanceConflict):
        save_policy(owner, "disabled", unset["revision"], org.id)
    global_relaxed = save_policy(admin, "personal_allowed", default["revision"])
    refreshed = get_policy(owner, org.id)
    assert refreshed["effective_mode"] == "personal_allowed" and refreshed["revision"] != relaxed["revision"]
    with pytest.raises(AppGovernanceConflict):
        save_policy(owner, "disabled", relaxed["revision"], org.id)
    restricted = save_policy(owner, "disabled", refreshed["revision"], org.id)
    assert restricted["effective_mode"] == "disabled"
    inherited = save_policy(owner, None, restricted["revision"], org.id)
    assert inherited["mode"] is None and inherited["effective_mode"] == "personal_allowed"
    assert inherited["revision"] != unset["revision"]
    disabled = save_policy(admin, "disabled", global_relaxed["revision"])
    assert disabled["effective_mode"] == get_policy(owner, org.id)["effective_mode"] == "disabled"
    with pytest.raises(ValueError):
        save_policy(admin, None, disabled["revision"])


def test_current_authority_and_active_organization(governance):
    _, (admin, owner, outsider), org, *_ = governance
    for operation in (
        lambda: get_policy(owner),
        lambda: get_policy(outsider, org.id),
        lambda: save_policy(outsider, "disabled", "0" * 64, org.id),
    ):
        with pytest.raises(AppGovernanceDenied):
            operation()
    current = get_policy(admin)
    with DbSession.atomic() as db:
        admin.is_admin = False
        db.update(admin)
    with pytest.raises(AppGovernanceDenied):
        save_policy(admin, "disabled", current["revision"])
    with DbSession.atomic() as db:
        org.is_active = False
        db.update(org)
    with pytest.raises(AppGovernanceDenied):
        get_policy(owner, org.id)


def test_managed_organization_discovery_is_bounded_current_and_private(governance):
    _, (admin, owner, outsider), org, *_ = governance
    assert list_managed_organizations(owner) == {"items": [{"uid": org.get_uid(), "name": "Org"}], "next_cursor": None}
    first = list_managed_organizations(admin, limit=1)
    assert first["items"] == [{"uid": org.get_uid(), "name": "Org"}]
    assert first["next_cursor"] == org.get_uid()
    second = list_managed_organizations(admin, limit=1, after_uid=first["next_cursor"])
    assert [row["name"] for row in second["items"]] == ["Other"]
    assert second["next_cursor"] is None
    assert [row["name"] for row in list_managed_organizations(outsider)["items"]] == ["Other"]
    with DbSession.atomic() as db:
        org.suspended_at = SafeDateTime.now()
        admin.is_admin = False
        db.update(org)
        db.update(admin)
    assert list_managed_organizations(owner)["items"] == []
    assert list_managed_organizations(admin)["items"] == []
    with DbSession.atomic() as db:
        outsider.activated_at = None
        db.update(outsider)
    with pytest.raises(AppGovernanceDenied):
        list_managed_organizations(outsider)
    for limit in (0, 51, True):
        with pytest.raises(ValueError):
            list_managed_organizations(owner, limit=limit)


def test_connection_policy_privacy_and_unattended_ownership(governance):
    _, (admin, owner, outsider), org, project, personal, shared = governance
    default = get_policy(admin)
    save_policy(admin, "personal_allowed", default["revision"])
    with DbSession.atomic() as db:
        assert require_connection_access(db, owner, project, personal).id == personal.id
        assert require_connection_access(db, owner, project, shared, unattended=True).id == shared.id
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, personal, unattended=True)
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=admin.id))
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, admin, project, personal)
        shared.organization_id = 11
        db.update(shared)
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, shared)
    global_policy = get_policy(admin)
    save_policy(admin, "approved_only", global_policy["revision"])
    with DbSession.atomic() as db:
        with pytest.raises(AppGovernanceDenied):
            require_app_allowed(db, project, approved=False)
        assert require_connection_access(db, owner, project, personal).id == personal.id
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, personal, personal_app=True)
    with DbSession.atomic() as db:
        owner.activated_at = None
        db.update(owner)
    with DbSession.atomic() as db:
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, personal)


@pytest.mark.parametrize("ownership,organization_id", [("personal", 10), ("organization", None), ("invalid", None)])
def test_database_ownership_constraint(governance, ownership, organization_id):
    engine = governance[0]
    with pytest.raises(IntegrityError), Session(engine) as db:
        db.add(
            AppConnection(id=90, app_key="example", owner_id=2, ownership=ownership, organization_id=organization_id)
        )
        db.commit()


def test_policy_scope_unique_and_consistent(governance):
    engine = governance[0]
    get = get_policy(governance[1][0])
    save_policy(governance[1][0], "approved_only", get["revision"])
    with pytest.raises(IntegrityError), Session(engine) as db:
        db.add(AppGovernancePolicy(id=99, scope_key="global", mode="disabled"))
        db.commit()
    with pytest.raises(IntegrityError), Session(engine) as db:
        db.add(AppGovernancePolicy(id=98, scope_key="global", organization_id=10))
        db.commit()


def test_migration_preserves_personal_owner_and_protects_shared_rows():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    Organization.__table__.create(engine)
    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20261010010000-d73ef84a91c2.py"
    spec = importlib.util.spec_from_file_location("governance_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE app_connection (id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL)"))
        connection.execute(text("INSERT INTO app_connection VALUES (1, 42)"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.execute(text("SELECT owner_id,ownership,organization_id FROM app_connection")).one() == (
            42,
            "personal",
            None,
        )
        assert set(AppGovernancePolicy.__table__.columns.keys()) == {
            c["name"] for c in inspect(connection).get_columns("app_governance_policy")
        }
        connection.execute(text("UPDATE app_connection SET ownership='organization', organization_id=10"))
        with pytest.raises(RuntimeError, match="organization connection"):
            module.downgrade()
        connection.execute(text("UPDATE app_connection SET ownership='personal', organization_id=NULL"))
        module.downgrade()
        assert connection.execute(text("SELECT owner_id FROM app_connection")).scalar() == 42
    engine.dispose()


def test_http_policy_routes_current_admin_owner_and_stale_revision(governance):
    import langboard.routes.settings.AppGovernanceSettingsApi  # noqa: F401
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    _, (admin, owner, outsider), org, *_ = governance
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    with TestClient(app) as client:

        def request(actor, method, path, **kwargs):
            access, refresh = AuthSecurity.authenticate(actor.id)
            client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
            return client.request(method, path, headers={"Authorization": f"Bearer {access}"}, **kwargs)

        path = "/settings/apps/governance"
        organizations_path = f"{path}/organizations"
        managed = request(owner, "GET", organizations_path)
        assert managed.status_code == 200
        assert managed.json() == {"items": [{"uid": org.get_uid(), "name": "Org"}], "next_cursor": None}
        first = request(admin, "GET", organizations_path, params={"limit": 1})
        assert first.status_code == 200 and first.json()["next_cursor"] == org.get_uid()
        next_page = request(admin, "GET", organizations_path, params={"limit": 1, "cursor": org.get_uid()})
        assert next_page.status_code == 200 and next_page.json()["items"][0]["name"] == "Other"
        assert request(owner, "GET", organizations_path, params={"limit": 51}).status_code in (400, 422)
        assert request(owner, "GET", organizations_path, params={"cursor": "bad cursor"}).status_code == 400
        response = request(admin, "GET", path)
        assert response.status_code == 200
        initial = response.json()
        assert set(initial) == {"mode", "effective_mode", "revision"}
        saved = request(admin, "PUT", path, json={"mode": "personal_allowed", "expected_revision": initial["revision"]})
        assert saved.status_code == 200 and saved.json()["mode"] == "personal_allowed"
        assert (
            request(admin, "PUT", path, json={"mode": "disabled", "expected_revision": initial["revision"]}).status_code
            == 409
        )
        assert request(owner, "GET", path).status_code == 403
        org_path = f"{path}/organizations/{org.get_uid()}"
        org_policy = request(owner, "GET", org_path)
        assert org_policy.status_code == 200 and org_policy.json()["mode"] is None
        assert request(outsider, "GET", org_path).status_code == 403
        assert (
            request(
                owner, "PUT", org_path, json={"mode": "disabled", "expected_revision": org_policy.json()["revision"]}
            ).status_code
            == 200
        )
        current = request(owner, "GET", org_path).json()
        inherited = request(owner, "PUT", org_path, json={"mode": None, "expected_revision": current["revision"]})
        assert inherited.status_code == 200 and inherited.json()["mode"] is None
        assert request(
            admin, "PUT", path, json={"mode": "invalid", "expected_revision": initial["revision"]}
        ).status_code in (400, 422)


def test_runtime_policy_reads_do_not_lock_global_or_organization_rows(governance, monkeypatch):
    from sqlalchemy.dialects import postgresql

    _, (admin, owner, _), org, project, *_ = governance
    policy = get_policy(admin)
    save_policy(admin, "approved_only", policy["revision"])
    statements = []
    original = DbSession.exec

    def record(db, statement, **kwargs):
        statements.append(str(statement.compile(dialect=postgresql.dialect())))
        return original(db, statement, **kwargs)

    monkeypatch.setattr(DbSession, "exec", record)
    with DbSession.atomic() as db:
        assert current_policy(db, org.id)["effective_mode"] == "approved_only"
        assert require_app_allowed(db, project)["effective_mode"] == "approved_only"
    assert statements and all("FOR UPDATE" not in statement for statement in statements)
    assert any("app_governance_policy" in statement for statement in statements)
    assert any("organization" in statement for statement in statements)
    statements.clear()
    get_policy(owner, org.id)
    assert any("app_governance_policy" in statement and "FOR UPDATE" in statement for statement in statements)
    assert any("organization" in statement and "FOR UPDATE" in statement for statement in statements)


def test_policy_change_invalidates_open_panels_only_after_commit(governance, monkeypatch):
    from langboard_shared.publishers import AppSettingPublisher

    _, (admin, owner, _), org, *_ = governance
    events = []

    def published():
        # A fresh primary read must observe the committed policy.
        with DbSession.use(readonly=False) as db:
            events.append(current_policy(db, org.id)["effective_mode"])

    monkeypatch.setattr(AppSettingPublisher, "apps_changed", published)
    baseline = get_policy(admin)
    saved = save_policy(admin, "disabled", baseline["revision"])
    assert events == ["disabled"]
    with pytest.raises(AppGovernanceConflict):
        save_policy(admin, "approved_only", baseline["revision"])
    assert events == ["disabled"]
    with pytest.raises(AppGovernanceDenied):
        save_policy(owner, "approved_only", saved["revision"])
    assert events == ["disabled"]
    inherited = get_policy(owner, org.id)
    save_policy(owner, "approved_only", inherited["revision"], org.id)
    assert events == ["disabled", "disabled"]


def test_personal_automation_is_denied_on_shared_board_without_organization(governance):
    _, (_, owner, collaborator), _, project, personal, _ = governance
    with DbSession.atomic() as db:
        project.organization_id = None
        db.update(project)
    with DbSession.atomic() as db:
        assert require_connection_access(db, owner, project, personal, unattended=True).id == personal.id
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=collaborator.id))
    with DbSession.atomic() as db:
        assert require_connection_access(db, owner, project, personal).id == personal.id
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, personal, unattended=True)


def test_deleted_board_cannot_use_app_policy_or_connections(governance):
    _, (_, owner, _), _, project, personal, _ = governance
    with DbSession.atomic() as db:
        project.deleted_at = SafeDateTime.now()
        db.update(project)
    with DbSession.atomic() as db:
        for operation in (
            lambda: require_app_allowed(db, project),
            lambda: require_connection_access(db, owner, project, personal),
            lambda: require_connection_access(db, owner, project, personal, unattended=True),
        ):
            with pytest.raises(AppGovernanceDenied):
                operation()


def test_personal_automation_requires_board_ownership(governance):
    _, (_, owner, other), _, project, personal, _ = governance
    with DbSession.atomic() as db:
        project.organization_id = None
        project.owner_id = other.id
        db.update(project)
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=owner.id))
    with DbSession.atomic() as db:
        assert require_connection_access(db, owner, project, personal).id == personal.id
        with pytest.raises(AppGovernanceDenied):
            require_connection_access(db, owner, project, personal, unattended=True)
