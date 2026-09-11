"""Replay-safety proof for external import lineage storage."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260910123000-54e9c7a1d230.py"
CHECKPOINT_MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260911071000-7c9e1ad4f620.py"


def load_migration(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_external_import_migration_is_replay_safe() -> None:
    migration = load_migration(MIGRATION, "external_import_migration")

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        assert sa.inspect(connection).has_table("external_import_record")

        migration.downgrade()
        migration.downgrade()
        assert not sa.inspect(connection).has_table("external_import_record")


def test_checkpoint_migration_repairs_an_older_canary_table() -> None:
    migration = load_migration(CHECKPOINT_MIGRATION, "external_import_checkpoint_migration")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE external_import_record (id BIGINT PRIMARY KEY, provenance TEXT NOT NULL DEFAULT '{}')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("external_import_record")}
        assert {"effects_dispatched_at", "effects_attempts", "effects_error"} <= columns

        migration.downgrade()
        migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("external_import_record")}
        assert not {"effects_dispatched_at", "effects_attempts", "effects_error"} & columns
