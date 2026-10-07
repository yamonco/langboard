# ruff: noqa: F811
"""Real host DB authority and storage behind metadata-only secret references."""

from types import SimpleNamespace
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from ....core.db import DbSession
from ....core.security import KeyVault
from ...models import Organization, SecretReference
from .SecretReferenceService import SecretReferenceConflict, SecretReferenceService, SecretReferenceUnavailable
from .WorkflowStageService import WorkflowStageService
from .WorkflowStageService_app_test import board  # noqa: F401


@pytest.fixture
def secrets(board, monkeypatch, tmp_path):
    from ....core.db.DbEngine import DbEngine
    from ....core.security.vault.LocalDevVaultProvider import LocalDevVaultProvider

    engine = DbEngine.get_main_engine()
    if engine.dialect.name == "sqlite":
        Organization.__table__.create(engine)
    # Exercise the actual migration, not just ORM metadata creation.
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration_path = (
        Path(__file__).resolve().parents[7] / "src/api/langboard/migrations/versions/20261008061000-820ebc13da57.py"
    )
    spec = importlib.util.spec_from_file_location("secret_reference_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    if engine.dialect.name == "postgresql":
        from sqlalchemy import text
        from sqlalchemy.schema import CreateColumn

        with engine.begin() as connection:
            for column in Organization.__table__.columns:
                if column.name != "id":
                    ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                    connection.execute(text("ALTER TABLE organization ADD COLUMN " + ddl))
    monkeypatch.setattr(KeyVault, "provider", LocalDevVaultProvider(tmp_path))
    service = SecretReferenceService(
        lambda cls: board[0] if cls is WorkflowStageService else None, lambda _: None, None
    )
    return service, board, tmp_path


def test_personal_reference_redacts_locator_and_rechecks_current_actor(secrets):
    service, board, path = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "github/token", SecretStr("sensitive-fixture"))
    assert "locator" not in meta and "provider" not in meta
    assert service.resolve_for_runtime(actor, "secret://me/github/token").get_secret_value() == "sensitive-fixture"
    assert "sensitive-fixture" not in str(service.resolve_for_runtime(actor, meta["uri"]))
    with DbSession.use(readonly=False) as db:
        ref = db.exec(select(SecretReference)).first()[0]
        assert ref.locator not in str(ref.model_dump()) and ref.locator not in repr(ref)
        actor.activated_at = None
        db.update(actor)
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, meta["uri"])


def test_project_reference_requires_current_update_permission(secrets):
    service, board, path = secrets
    actor, project, role = board[1], board[2], board[4]
    with pytest.raises(SecretReferenceUnavailable):
        service.create(actor, "project", project.get_uid(), "github/key", SecretStr("private-key"))
    assert not list(path.iterdir())
    with DbSession.use(readonly=False) as db:
        role.actions = ["read", "update"]
        db.update(role)
    meta = service.create(actor, "project", project.get_uid(), "github/key", SecretStr("private-key"))
    assert (
        service.resolve_for_runtime(actor, f"secret://project/{project.get_uid()}/github/key").get_secret_value()
        == "private-key"
    )
    renamed = service.rename(actor, meta["uri"], "github/new-key", 0)
    assert renamed["uri"] == meta["uri"] and renamed["revision"] == 1
    with pytest.raises(SecretReferenceConflict):
        service.revoke(actor, meta["uri"], 0)
    with DbSession.use(readonly=False) as db:
        role.actions = ["read"]
        db.update(role)
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, meta["uri"])


def test_revoke_missing_provider_mismatch_and_dangling_deny(secrets):
    service, board, path = secrets
    actor = board[1]
    meta = service.create(actor, "personal", "me", "fixture", SecretStr("material"))
    with DbSession.use(readonly=False) as db:
        ref = db.exec(select(SecretReference)).first()[0]
    KeyVault.delete_key(ref.locator)
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, meta["uri"])
    KeyVault.store_secret(ref.locator, "material")
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, "secret://ref/zzzzzzzzzzz")
    original = KeyVault.provider
    KeyVault.provider = SimpleNamespace(name=lambda: "different-provider")
    try:
        with pytest.raises(SecretReferenceUnavailable):
            service.resolve_for_runtime(actor, meta["uri"])
    finally:
        KeyVault.provider = original
    service.revoke(actor, meta["uri"], 0)
    assert service.get_metadata(actor, meta["uri"])["state"] == "revoked"
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, meta["uri"])


def test_workspace_scope_rechecks_active_owner_and_foreign_actor(secrets):
    from sqlalchemy.orm import Session
    from ....core.db.DbEngine import DbEngine
    from ....core.types import SafeDateTime
    from ...models import User

    service, board, path = secrets
    with Session(DbEngine.get_main_engine(), expire_on_commit=False) as db:
        workspace = Organization(id=80, name="Workspace", slug="workspace", owner_user_id=1)
        db.add(workspace)
        db.commit()
    meta = service.create(board[1], "workspace", workspace.get_uid(), "github/key", SecretStr("key"))
    with DbSession.use(readonly=False) as db:
        other = db.exec(select(User).where(User.id == 2)).first()[0]
    with pytest.raises(SecretReferenceUnavailable):
        service.get_metadata(other, meta["uri"])
    with DbSession.use(readonly=False) as db:
        workspace.is_active = False
        workspace.suspended_at = SafeDateTime.now()
        db.update(workspace)
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(board[1], meta["uri"])


def test_duplicate_reference_rolls_back_new_secret_and_keeps_existing(secrets):
    from sqlalchemy.exc import IntegrityError

    service, board, path = secrets
    first = service.create(board[1], "personal", "me", "github/key", SecretStr("first"))
    with pytest.raises(IntegrityError):
        service.create(board[1], "personal", "me", "github/key", SecretStr("duplicate"))
    assert len(list(path.iterdir())) == 1
    assert service.resolve_for_runtime(board[1], first["uri"]).get_secret_value() == "first"


def test_move_requires_both_scopes_and_preserves_stable_uri(secrets):
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "github/key", SecretStr("key"))
    with pytest.raises(SecretReferenceUnavailable):
        service.move(board[1], meta["uri"], "project", board[2].get_uid(), 0)
    with DbSession.use(readonly=False) as db:
        board[4].actions = ["read", "update"]
        db.update(board[4])
    moved = service.move(board[1], meta["uri"], "project", board[2].get_uid(), 0)
    assert moved["uri"] == meta["uri"] and moved["revision"] == 1
    assert service.resolve_for_runtime(board[1], meta["uri"]).get_secret_value() == "key"
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(board[1], "secret://me/github/key")


def test_postgresql_same_revision_rename_serializes(secrets):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from ....core.db.DbEngine import DbEngine

    if DbEngine.get_main_engine().dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL")
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("key"))
    barrier = Barrier(2)

    def rename(name):
        barrier.wait(timeout=10)
        try:
            service.rename(board[1], meta["uri"], name, 0)
            return "renamed"
        except SecretReferenceConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(rename, name) for name in ("first", "second")]
        assert sorted(result.result(timeout=15) for result in results) == ["conflict", "renamed"]
    assert service.get_metadata(board[1], meta["uri"])["revision"] == 1
