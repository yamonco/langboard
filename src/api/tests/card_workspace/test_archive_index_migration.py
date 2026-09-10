"""Regression proof for the archive keyset pagination index."""

import importlib.util
from pathlib import Path
from types import ModuleType
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260910183000-4e8b1c7d2a90.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("archive_page_index", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_page_index_upgrade_and_downgrade() -> None:
    migration = _migration()
    metadata = sa.MetaData()
    sa.Table(
        "card",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        indexes = {index["name"]: index for index in sa.inspect(connection).get_indexes("card")}
        assert indexes["ix_card_project_archive_page"]["column_names"] == ["project_id", "archived_at", "id"]

        migration.downgrade()
        migration.downgrade()
        assert "ix_card_project_archive_page" not in {
            index["name"] for index in sa.inspect(connection).get_indexes("card")
        }


def test_archive_page_index_reaches_the_canary_merge_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src/api/langboard/migrations"))

    assert ScriptDirectory.from_config(config).get_heads() == ["8a9f1a5a9599"]
