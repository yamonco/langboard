# ruff: noqa: F811
"""Native app credentials never inherit user authentication or capabilities."""

from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
from langboard.routes.settings import AppConnectionCredentialApi, AppConnectionIdentityApi  # noqa: F401
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.routing import AppRouter
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    AppConnection,
    AppConnectionCredential,
    AppDefinition,
    AppGovernancePolicy,
    Organization,
    User,
)
from langboard_shared.domain.services import AppConnectionAuthentication as auth
from langboard_shared.domain.services.AppGovernance import AppGovernanceDenied
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from langboard_shared.Env import Env


DECLARATION = {
    "schema_version": 1,
    "key": "example-app",
    "version": "1.0.0",
    "name": "Example",
    "description": "Independent service",
    "capabilities": ["cards.create"],
    "resource_types": ["issue"],
}


def setup(actor):
    AppConnectionCredential.__table__.create(DbEngine.get_main_engine())
    with DbSession.atomic() as db:
        definition = AppDefinition(key="example-app", approved_by=actor.id, declaration=DECLARATION)
        db.insert(definition)
        connection = AppConnection(app_key="example-app", owner_id=actor.id, state="connected")
        db.insert(connection)
    return connection, definition


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_hash_identity_management_and_idempotent_revocation(board):
    actor = board[1]
    connection, _ = setup(actor)
    issued = auth.issue_connection_credential(actor, connection.id)
    principal = auth.authenticate_connection_credential(issued["token"])
    assert principal.app_key == "example-app" and principal.connection_id == connection.id
    with DbSession.use(readonly=False) as db:
        row = db.exec(SqlBuilder.select.table(AppConnectionCredential)).first()
        assert len(row.token_hash) == 64 and row.token_hash != issued["token"]
        assert issued["token"] not in repr(row)
    with pytest.raises(AppGovernanceDenied):
        auth.issue_connection_credential(SimpleNamespace(id=board[2].owner_id), connection.id)
    auth.revoke_connection_credential(actor, connection.id, principal.credential_id)
    auth.revoke_connection_credential(actor, connection.id, principal.credential_id)
    with pytest.raises(AppGovernanceDenied):
        auth.authenticate_connection_credential(issued["token"])


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
@pytest.mark.parametrize(
    "revoked", ["connection", "definition", "owner", "expiry", "token", "identity", "trust", "reconnected"]
)
def test_current_revocation_and_trust_change(board, revoked):
    actor = board[1]
    connection, definition = setup(actor)
    issued = auth.issue_connection_credential(actor, connection.id)
    with DbSession.atomic() as db:
        if revoked == "connection":
            connection.state = "revoked"
            db.update(connection)
        elif revoked == "definition":
            definition.is_enabled = False
            db.update(definition)
        elif revoked == "owner":
            current = db.exec(SqlBuilder.select.table(User).where(User.id == actor.id)).first()
            current.activated_at = None
            db.update(current)
        elif revoked == "expiry":
            row = db.exec(SqlBuilder.select.table(AppConnectionCredential)).first()
            row.expires_at = SafeDateTime.fromisoformat("2020-01-01T00:00:00+00:00")
            db.update(row)
        elif revoked == "identity":
            connection.external_account_id = "different-account"
            db.update(connection)
        elif revoked == "trust":
            definition.declaration = {**DECLARATION, "publisher": "Another publisher"}
            db.update(definition)
        elif revoked == "reconnected":
            connection.state = "revoked"
            db.update(connection)
    if revoked == "reconnected":
        with DbSession.atomic() as db:
            connection.state = "connected"
            db.update(connection)
    token = issued["token"] if revoked != "token" else "lbac_" + "x" * 43
    with pytest.raises(AppGovernanceDenied):
        auth.authenticate_connection_credential(token)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_same_trust_version_update_preserves_connection_identity(board):
    actor = board[1]
    connection, definition = setup(actor)
    issued = auth.issue_connection_credential(actor, connection.id)
    with DbSession.atomic() as db:
        definition.declaration = {**DECLARATION, "version": "1.0.1"}
        definition.generation += 1
        db.update(definition)
    assert auth.authenticate_connection_credential(issued["token"]).connection_id == connection.id


@pytest.mark.parametrize("board", ["sqlite-http"], indirect=True)
def test_http_credential_cannot_impersonate_user(board, monkeypatch):
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    actor = board[1]
    connection, _ = setup(actor)
    app = FastAPI()
    app.include_router(AppRouter.api)
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    path = f"/settings/apps/connections/{connection.get_uid()}/credentials"
    with TestClient(app) as client:
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        issued = client.post(path, json={"expires_in_seconds": 3600}, headers={"Authorization": f"Bearer {access}"})
        assert issued.status_code == 200 and issued.headers["cache-control"] == "no-store"
        token = issued.json()["token"]
        listed = client.get(path, headers={"Authorization": f"Bearer {access}"})
        assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
        assert listed.json()["items"][0]["credential_uid"] == issued.json()["credential_uid"]
        assert token not in listed.text and "token_hash" not in listed.text
        identity = client.get("/apps/v1/identity", headers={"Authorization": f"Bearer {token}", "X-App-Key": "spoofed"})
        assert identity.status_code == 200 and identity.json()["app_key"] == "example-app"
        assert "token" not in identity.json()
        assert client.post(path, json={}, headers={"Authorization": f"Bearer {token}"}).status_code != 200
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        revoked = client.post(
            path + "/" + issued.json()["credential_uid"] + "/revoke", headers={"Authorization": f"Bearer {access}"}
        )
        assert revoked.status_code == 200
        assert client.get("/apps/v1/identity", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        owner_history = client.get(path, headers={"Authorization": f"Bearer {access}"})
        assert owner_history.json()["items"][0]["revoked_at"] is not None


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_migration_creates_hash_storage_and_preserves_history(board):
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = importlib.import_module("langboard.migrations.versions.20261011011500-f26c137450a8")
    engine = DbEngine.get_main_engine()
    original = module.op
    try:
        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
        actor = board[1]
        with DbSession.atomic() as db:
            db.insert(AppDefinition(key="example-app", approved_by=actor.id, declaration=DECLARATION))
            app_connection = AppConnection(app_key="example-app", owner_id=actor.id, state="connected")
            db.insert(app_connection)
        issued = auth.issue_connection_credential(actor, app_connection.id)
        assert auth.authenticate_connection_credential(issued["token"]).app_key == "example-app"
        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="credential history"):
                module.downgrade()
    finally:
        module.op = original


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_organization_owner_and_current_policy_gate_credentials(board):
    actor = board[1]
    Organization.__table__.create(DbEngine.get_main_engine())
    connection, _ = setup(actor)
    with DbSession.atomic() as db:
        organization = Organization(name="Example organization", slug="example", owner_user_id=actor.id)
        db.insert(organization)
        connection.ownership = "organization"
        connection.organization_id = organization.id
        db.update(connection)
    issued = auth.issue_connection_credential(actor, connection.id)
    assert auth.authenticate_connection_credential(issued["token"]).organization_id == organization.id
    with pytest.raises(AppGovernanceDenied):
        auth.issue_connection_credential(SimpleNamespace(id=board[2].owner_id), connection.id)
    with DbSession.atomic() as db:
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
    with pytest.raises(AppGovernanceDenied):
        auth.authenticate_connection_credential(issued["token"])
    # Management can still revoke after policy disablement.
    with DbSession.use(readonly=False) as db:
        credential_id = db.exec(SqlBuilder.select.table(AppConnectionCredential)).first().id
    auth.revoke_connection_credential(actor, connection.id, credential_id)


@pytest.mark.parametrize("board", ["sqlite://"], indirect=True)
def test_credential_history_is_owner_scoped_paged_and_revocable_after_disable(board):
    actor = board[1]
    connection, definition = setup(actor)
    issued = [auth.issue_connection_credential(actor, connection.id) for _ in range(3)]
    with DbSession.atomic() as db:
        other = AppConnection(app_key=connection.app_key, owner_id=actor.id, state="connected")
        db.insert(other)
    other_token = auth.issue_connection_credential(actor, other.id)["token"]
    first = auth.list_connection_credentials(actor, connection.id, limit=2)
    second = auth.list_connection_credentials(
        actor, connection.id, after_id=SnowflakeID.from_short_code(first["next_cursor"]), limit=2
    )
    assert [row["credential_uid"] for row in first["items"] + second["items"]] == [
        row["credential_uid"] for row in issued
    ]
    assert second["next_cursor"] is None
    assert other_token not in str(first)
    with pytest.raises(AppGovernanceDenied):
        auth.list_connection_credentials(SimpleNamespace(id=board[2].owner_id), connection.id)
    with DbSession.atomic() as db:
        definition.is_enabled = False
        db.update(definition)
        connection.state = "disconnected"
        db.update(connection)
    assert len(auth.list_connection_credentials(actor, connection.id)["items"]) == 3
    auth.revoke_connection_credential(actor, connection.id, SnowflakeID.from_short_code(issued[0]["credential_uid"]))
    assert auth.list_connection_credentials(actor, connection.id)["items"][0]["revoked_at"]
