"""The optional anchor column can be added and removed without replacing comments."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION = Path(__file__).parent / "versions/20260911160000-c7b0d5a6e491.py"


def test_anchor_migration_upgrades_and_downgrades() -> None:
    spec = importlib.util.spec_from_file_location("card_comment_anchor_migration", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE card_comment (id INTEGER PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "anchor" in {column["name"] for column in sa.inspect(connection).get_columns("card_comment")}
        migration.downgrade()
        assert "anchor" not in {column["name"] for column in sa.inspect(connection).get_columns("card_comment")}
