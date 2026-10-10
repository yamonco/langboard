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

    for filename in (
        "20261008061000-820ebc13da57.py",
        "20261008065000-932fcd24eb68.py",
        "20261008072000-a430de35fc79.py",
        "20261008114000-e87412793ab3.py",
        "20261009040000-7c98451eab03.py",
        "20261009100000-b51832cfe4a7.py",
        "20261010212000-e15b02634f97.py",
    ):
        migration_path = Path(__file__).resolve().parents[7] / "src/api/langboard/migrations/versions" / filename
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
    from ...models import AppGovernancePolicy
    with DbSession.use(readonly=False) as db:
        db.insert(AppGovernancePolicy(scope_key="global", mode="disabled"))
    assert service.get_metadata(actor, meta["uri"])["revision"] == 1
    renamed = service.rename(actor, meta["uri"], "github/independent-key", 1)
    assert renamed["revision"] == 2
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


def test_audit_tracks_source_revision_and_no_credential_fields(secrets):
    from ...models import SecretReferenceAudit
    from .SecretReferenceService import SecretAuditSource

    service, board, path = secrets
    actor = board[1]
    source = SecretAuditSource("app_connection", "installation_42")
    meta = service.create(actor, "personal", "me", "github/key", SecretStr("fixture-private-material"), source=source)
    service.resolve_for_runtime(actor, meta["uri"], source=source)
    service.rename(actor, meta["uri"], "github/new", 0, source=source)
    service.move(actor, meta["uri"], "personal", "me", 1, source=source)
    service.revoke(actor, meta["uri"], 2, source=source)
    with DbSession.use(readonly=False) as db:
        rows = [row[0] for row in db.exec(select(SecretReferenceAudit).order_by(SecretReferenceAudit.id)).all()]
    assert [row.action for row in rows] == ["created", "resolved", "renamed", "moved", "revoked"]
    assert [row.reference_revision for row in rows] == [0, 0, 1, 2, 3]
    assert all(row.actor_id == actor.id and row.source_uid == "installation_42" for row in rows)
    assert "fixture-private-material" not in str([row.model_dump() for row in rows])
    assert not {"locator", "provider", "value", "payload"} & set(SecretReferenceAudit.model_fields)
    with pytest.raises(SecretReferenceUnavailable):
        service.resolve_for_runtime(actor, meta["uri"], source=source)
    with DbSession.use(readonly=False) as db:
        assert len(db.exec(select(SecretReferenceAudit)).all()) == 5


@pytest.mark.parametrize("kind,uid", [("unknown", "x"), ("runtime", "https://unsafe/path"), ("api", "x" * 65)])
def test_audit_source_rejects_freeform_payload(kind, uid):
    from .SecretReferenceService import SecretAuditSource

    with pytest.raises(ValueError):
        SecretAuditSource(kind, uid)


def test_audit_failure_rolls_back_reference_and_new_storage(secrets, monkeypatch):
    service, board, path = secrets

    def fail(*args):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.create(board[1], "personal", "me", "fixture", SecretStr("material"))
    assert not list(path.iterdir())
    with DbSession.use(readonly=False) as db:
        assert not db.exec(select(SecretReference)).all()


def test_rotation_keeps_uri_retires_old_material_and_rejects_stale_revision(secrets):
    from ...models import SecretReferenceAudit

    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("old"))
    original_paths = set(path.iterdir())
    rotated = service.rotate(board[1], meta["uri"], SecretStr("new"), 0)
    assert rotated["uri"] == meta["uri"] and rotated["revision"] == 1
    assert not original_paths & set(path.iterdir()) and len(list(path.iterdir())) == 1
    assert service.resolve_for_runtime(board[1], meta["uri"]).get_secret_value() == "new"
    with pytest.raises(SecretReferenceConflict):
        service.rotate(board[1], meta["uri"], SecretStr("stale"), 0)
    assert len(list(path.iterdir())) == 1
    with DbSession.use(readonly=False) as db:
        audit = db.exec(select(SecretReferenceAudit).where(SecretReferenceAudit.action == "rotated")).first()[0]
    assert audit.reference_revision == 1


def test_rotation_audit_failure_preserves_existing_material(secrets, monkeypatch):
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("old"))
    original_paths = set(path.iterdir())
    original = service._audit

    def fail(db, actor, reference, action, source):
        if action == "rotated":
            raise RuntimeError("audit unavailable")
        return original(db, actor, reference, action, source)

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.rotate(board[1], meta["uri"], SecretStr("new"), 0)
    assert set(path.iterdir()) == original_paths
    assert service.get_metadata(board[1], meta["uri"])["revision"] == 0
    assert service.resolve_for_runtime(board[1], meta["uri"]).get_secret_value() == "old"


def test_revoked_rotation_cannot_restore_access(secrets):
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("old"))
    service.revoke(board[1], meta["uri"], 0)
    with pytest.raises(SecretReferenceUnavailable):
        service.rotate(board[1], meta["uri"], SecretStr("new"), 1)


def test_retired_material_cleanup_failure_keeps_new_reference_valid(secrets, monkeypatch):
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("old"))
    monkeypatch.setattr(
        KeyVault.provider, "delete_key", lambda *_: (_ for _ in ()).throw(RuntimeError("cleanup unavailable"))
    )
    rotated = service.rotate(board[1], meta["uri"], SecretStr("new"), 0)
    assert rotated["revision"] == 1
    assert service.resolve_for_runtime(board[1], meta["uri"]).get_secret_value() == "new"
    assert len(list(path.iterdir())) == 2


def test_storage_writes_reject_outer_transaction_before_vault_effect(secrets):
    service, board, path = secrets
    meta = service.create(board[1], "personal", "me", "fixture", SecretStr("old"))
    original_paths = set(path.iterdir())
    with DbSession.atomic():
        with pytest.raises(RuntimeError, match="own its transaction"):
            service.create(board[1], "personal", "me", "other", SecretStr("other"))
        with pytest.raises(RuntimeError, match="own its transaction"):
            service.rotate(board[1], meta["uri"], SecretStr("new"), 0)
    assert set(path.iterdir()) == original_paths


@pytest.fixture
def provider_migration(secrets, monkeypatch, tmp_path):
    from ....core.security.vault.LocalDevVaultProvider import LocalDevVaultProvider

    class DestinationProvider(LocalDevVaultProvider):
        def name(self):
            return "fixture-destination"

    service, board, path = secrets
    actor = board[1]
    old = KeyVault.provider
    meta = service.create(actor, "personal", "me", "migration/key", SecretStr("fixture-migration-material"))
    target = DestinationProvider(tmp_path / "destination")
    monkeypatch.setattr(KeyVault, "provider", target)
    return service, board, path, old, target, meta


def test_provider_migration_keeps_identity_revision_audit_and_verified_material(provider_migration):
    service, board, path, old, target, meta = provider_migration
    migrated = service.migrate_provider(board[1], meta["uri"], 0, old)
    assert migrated == {**meta, "revision": 1}
    assert not [item for item in path.iterdir() if item.is_file()] and len(list(target.base_dir.iterdir())) == 1
    assert service.resolve_for_runtime(board[1], migrated["uri"]).get_secret_value() == "fixture-migration-material"
    history = service.list_audit(board[1], migrated["uri"])
    event = next(row for row in history["items"] if row["action"] == "migrated")
    assert (event["revision_before"], event["revision_after"], event["reason_code"]) == (0, 1, "provider_migrated")
    assert not any(
        word in str(history) + str(migrated)
        for word in ["fixture-migration-material", "fixture-destination", "locator"]
    )


@pytest.mark.parametrize(
    "failure", ["denied", "stale", "wrong-provider", "revoked", "outer-transaction", "readback", "audit"]
)
def test_provider_migration_failure_preserves_source_and_discards_uncommitted_destination(
    provider_migration, monkeypatch, failure
):
    service, board, path, old, target, meta = provider_migration
    actor, revision, expected = board[1], 0, Exception
    original_paths = {item for item in path.iterdir() if item.is_file()}
    if failure == "denied":
        actor, expected = board[3], SecretReferenceUnavailable
    elif failure == "stale":
        revision, expected = 5, SecretReferenceConflict
    elif failure == "wrong-provider":
        monkeypatch.setattr(old, "name", lambda: "wrong-source")
        expected = SecretReferenceUnavailable
    elif failure == "revoked":
        service.revoke(actor, meta["uri"], 0)
        revision, expected = 1, SecretReferenceUnavailable
    elif failure == "readback":
        monkeypatch.setattr(target, "get_key", lambda *_: "different-material")
        expected = SecretReferenceUnavailable
    elif failure == "audit":
        monkeypatch.setattr(service, "_audit", lambda *_: (_ for _ in ()).throw(RuntimeError("audit failed")))
        expected = RuntimeError
    if failure == "outer-transaction":
        with DbSession.atomic(), pytest.raises(RuntimeError, match="own its transaction"):
            service.migrate_provider(actor, meta["uri"], revision, old)
    else:
        with pytest.raises(expected):
            service.migrate_provider(actor, meta["uri"], revision, old)
    assert {item for item in path.iterdir() if item.is_file()} == original_paths
    assert not list(target.base_dir.iterdir())
    with DbSession.use(readonly=False) as db:
        reference = db.exec(select(SecretReference)).first()[0]
    assert reference.provider == "local-dev"
    assert reference.revision == (1 if failure == "revoked" else 0)


def test_provider_migration_retirement_failure_keeps_committed_destination(provider_migration, monkeypatch):
    service, board, path, old, target, meta = provider_migration
    monkeypatch.setattr(old, "delete_key", lambda *_: (_ for _ in ()).throw(RuntimeError("retirement failed")))
    migrated = service.migrate_provider(board[1], meta["uri"], 0, old)
    assert migrated["revision"] == 1
    assert [item for item in path.iterdir() if item.is_file()] and list(target.base_dir.iterdir())
    assert service.resolve_for_runtime(board[1], meta["uri"]).get_secret_value() == "fixture-migration-material"


def test_provider_migration_schema_roundtrip_preserves_old_facts_and_guards_new_facts(provider_migration, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from ....core.db.DbEngine import DbEngine

    service, board, path, old, target, meta = provider_migration
    filename = (
        Path(__file__).resolve().parents[7] / "src/api/langboard/migrations/versions/20261009100000-b51832cfe4a7.py"
    )
    spec = importlib.util.spec_from_file_location("provider_migration_audit", filename)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    before = service.list_audit(board[1], meta["uri"])
    with DbEngine.get_main_engine().begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        migration.upgrade()
    assert service.list_audit(board[1], meta["uri"]) == before
    service.migrate_provider(board[1], meta["uri"], 0, old)
    with DbEngine.get_main_engine().begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
    assert service.list_audit(board[1], meta["uri"])["items"][0]["action"] == "migrated"
