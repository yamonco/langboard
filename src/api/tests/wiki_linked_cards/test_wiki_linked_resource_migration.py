"""Replay-safety proof for linked Wiki card identity."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260910103000-3a6f8c1d2e4b.py"


def test_linked_resource_migration_reconciles_preexisting_columns() -> None:
    spec = importlib.util.spec_from_file_location("linked_resource_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    metadata = sa.MetaData()
    sa.Table(
        "card",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_uid", sa.String(), nullable=True),
        sa.UniqueConstraint("project_id", "source_type", "source_uid", name="uq_card_linked_resource"),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        constraints = sa.inspect(connection).get_check_constraints("card")
        assert {constraint["name"] for constraint in constraints} == {"ck_card_linked_source_complete"}

        migration.downgrade()
        migration.downgrade()
        assert {column["name"] for column in sa.inspect(connection).get_columns("card")} == {
            "id",
            "project_id",
        }
