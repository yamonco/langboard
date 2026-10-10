# ruff: noqa: F811
"""Native same-scope copy persists paired audit facts without exposing material."""

import json
from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.security import KeyVault
from langboard_shared.domain.models import SecretReference, SecretReferenceAudit
from langboard_shared.domain.services.factory.SecretReferenceService import (
    SecretReferenceConflict,
    SecretReferenceUnavailable,
)
from langboard_shared.domain.services.factory.SecretReferenceService_test import secrets  # noqa: F401
from langboard_shared.domain.services.factory.WorkflowStageService_app_test import board  # noqa: F401
from pydantic import SecretStr


def test_copy_has_independent_identity_storage_and_paired_history(secrets):
    service, board, _ = secrets
    actor = board[1]
    original = service.create(actor, "personal", "me", "copy/original", SecretStr("material-fixture"))
    copied = service.copy(actor, original["uri"], "copy/duplicate", 0)
    assert copied["uri"] != original["uri"] and copied["revision"] == 0
    assert (copied["scope"], copied["scope_uid"]) == (original["scope"], original["scope_uid"])
    with DbSession.use(readonly=False) as db:
        refs = db.exec(SqlBuilder.select.table(SecretReference)).all()
        assert len({r.locator for r in refs}) == 2
    source = service.list_audit(actor, original["uri"])["items"][0]
    target = service.list_audit(actor, copied["uri"])["items"][0]
    assert source["action"] == "copied" and target["action"] == "created"
    assert source["request_id"] == target["request_id"]
    assert source["reason_code"] == target["reason_code"] == "reference_copied"
    assert source["revision_before"] == source["revision_after"] == 0
    assert target["revision_before"] is None
    assert "material-fixture" not in json.dumps([copied, source, target])
    service.revoke(actor, original["uri"], 0)
    assert service.resolve_for_runtime(actor, copied["uri"]).get_secret_value() == "material-fixture"


@pytest.mark.parametrize("failure", ["foreign", "inactive", "revoked", "stale", "provider", "missing", "duplicate"])
def test_copy_failures_preserve_source_and_do_not_leave_new_material(secrets, failure, monkeypatch):
    service, board, path = secrets
    actor = board[1]
    original = service.create(actor, "personal", "me", "copy/original", SecretStr("material-fixture"))
    if failure == "foreign":
        actor = board[3]
    elif failure == "inactive":
        with DbSession.use(readonly=False) as db:
            actor.activated_at = None
            db.update(actor)
    elif failure == "revoked":
        service.revoke(actor, original["uri"], 0)
    elif failure == "provider":
        monkeypatch.setattr(KeyVault, "provider", SimpleNamespace(name=lambda: "different"))
    elif failure == "missing":
        with DbSession.use(readonly=False) as db:
            ref = db.exec(SqlBuilder.select.table(SecretReference)).first()
        KeyVault.delete_key(ref.locator)
    before = {p.name for p in path.iterdir()}
    with DbSession.use(readonly=False) as db:
        audit_count = len(db.exec(SqlBuilder.select.table(SecretReferenceAudit)).all())
    from sqlalchemy.exc import IntegrityError

    with pytest.raises((SecretReferenceUnavailable, SecretReferenceConflict, IntegrityError)):
        service.copy(
            actor,
            original["uri"],
            "copy/original" if failure == "duplicate" else "copy/duplicate",
            1 if failure == "stale" else original["revision"] + (failure == "revoked"),
        )
    assert {p.name for p in path.iterdir()} == before
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(SecretReference)).all()) == 1
        assert len(db.exec(SqlBuilder.select.table(SecretReferenceAudit)).all()) == audit_count


def test_copy_audit_failure_rolls_back_both_references_and_vault(secrets, monkeypatch):
    service, board, path = secrets
    actor = board[1]
    original = service.create(actor, "personal", "me", "copy/original", SecretStr("material-fixture"))
    before = {p.name for p in path.iterdir()}
    native_audit = service._audit

    def failing_audit(db, actor, reference, action, source):
        native_audit(db, actor, reference, action, source)
        if action == "created":
            raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "_audit", failing_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.copy(actor, original["uri"], "copy/duplicate", 0)
    assert {p.name for p in path.iterdir()} == before
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(SqlBuilder.select.table(SecretReference)).all()) == 1
        assert len(db.exec(SqlBuilder.select.table(SecretReferenceAudit)).all()) == 1


@pytest.mark.parametrize("board", ["sqlite-http", "postgresql-test"], indirect=True)
def test_http_copy_rechecks_identity_revision_and_returns_only_metadata(secrets, monkeypatch):
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langboard.middlewares.ApiAuthMiddleware import ApiAuthMiddleware
    from langboard.routes.account.SecretReferenceApi import copy_secret_reference
    from langboard_shared.core.caching import Cache
    from langboard_shared.core.db.DbEngine import DbEngine
    from langboard_shared.core.routing import AppRouter
    from langboard_shared.core.security import AuthSecurity
    from langboard_shared.Env import Env

    secret_service, board, _ = secrets
    actor = board[1]
    original = secret_service.create(actor, "personal", "me", "copy/http", SecretStr("material-fixture"))
    service = SimpleNamespace(secret_reference=secret_service, close=lambda: None)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", DbEngine.get_main_engine)
    monkeypatch.setattr(Cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(Cache, "set", lambda *a, **k: None)
    monkeypatch.setattr(
        importlib.import_module("langboard.middlewares.ApiAuthMiddleware"), "DomainService", lambda: service
    )
    app = FastAPI()
    app.include_router(AppRouter.api)
    for route in app.routes:
        if getattr(route, "endpoint", None) is copy_secret_reference:
            for dep in route.dependant.dependencies:
                if dep.name == "service":
                    app.dependency_overrides[dep.call] = lambda: service
    app.add_middleware(ApiAuthMiddleware, routes=AppRouter.api.routes)
    access, refresh = AuthSecurity.authenticate(actor.id)
    headers = {"Authorization": f"Bearer {access}"}
    path = "/secret-references/" + original["uri"].rsplit("/", 1)[1] + "/copy"
    form = {"name": "copy/http-new", "expected_revision": 0}
    with TestClient(app) as client:
        assert client.post(path, json=form).status_code == 401
        client.cookies.set(Env.REFRESH_TOKEN_NAME, refresh)
        assert client.post(path, json={**form, "scope": "project"}, headers=headers).status_code == 400
        assert client.post(path, json={**form, "expected_revision": 1}, headers=headers).status_code == 409
        response = client.post(path, json=form, headers=headers)
        assert response.status_code == 201 and response.headers["cache-control"] == "no-store"
        assert response.json()["reference"]["uri"] != original["uri"]
        assert not any(word in response.text for word in ("material-fixture", "locator", "provider"))
        assert client.post(path, json=form, headers=headers).status_code == 409
        secret_service.revoke(actor, original["uri"], 0)
        assert (
            client.post(path, json={"name": "copy/revoked", "expected_revision": 1}, headers=headers).status_code == 404
        )


def test_copy_migration_retains_existing_facts_and_refuses_loss():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    metadata = sa.MetaData()
    table = sa.Table(
        "secret_reference_audit",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action", sa.String, nullable=False),
        sa.CheckConstraint(
            "action IN ('created','resolved','renamed','moved','revoked','rotated','bound','migrated')",
            name="ck_secret_reference_audit_action",
        ),
    )
    with sa.create_engine("sqlite://").begin() as connection:
        metadata.create_all(connection)
        connection.execute(table.insert().values(id=1, action="created"))
        path = (
            Path(__file__).resolve().parents[4] / "src/api/langboard/migrations/versions/20261010212000-e15b02634f97.py"
        )
        spec = importlib.util.spec_from_file_location("copy_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(sa.select(table.c.action)).scalars().all() == ["created"]
        connection.execute(table.insert().values(id=2, action="copied"))
        with pytest.raises(RuntimeError, match="Cannot discard secret copy audit facts"):
            migration.downgrade()
        connection.execute(table.delete().where(table.c.id == 2))
        migration.downgrade()
        assert connection.execute(sa.select(table.c.action)).scalars().all() == ["created"]
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(table.insert().values(id=3, action="copied"))


def test_project_copy_preserves_scope_and_rechecks_update_permission(secrets):
    service, board, _ = secrets
    actor, project, role = board[1], board[2], board[4]
    with DbSession.use(readonly=False) as db:
        role.actions = ["read", "update"]
        db.update(role)
    original = service.create(actor, "project", project.get_uid(), "copy/source", SecretStr("project-material"))
    copied = service.copy(actor, original["uri"], "copy/target", 0)
    assert copied["scope"] == "project" and copied["scope_uid"] == project.get_uid()
    with DbSession.use(readonly=False) as db:
        role.actions = ["read"]
        db.update(role)
    with pytest.raises(SecretReferenceUnavailable):
        service.copy(actor, original["uri"], "copy/denied", 0)
