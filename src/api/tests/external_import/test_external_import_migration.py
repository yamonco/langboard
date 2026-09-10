"""Replay-safety proof for external import lineage storage."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260910123000-54e9c7a1d230.py"


def test_external_import_migration_is_replay_safe() -> None:
    spec = importlib.util.spec_from_file_location("external_import_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        assert sa.inspect(connection).has_table("external_import_record")

        migration.downgrade()
        migration.downgrade()
        assert not sa.inspect(connection).has_table("external_import_record")
