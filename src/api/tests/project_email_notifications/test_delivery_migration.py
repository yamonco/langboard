import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import BigInteger, Column, MetaData, Table, create_engine, inspect, select


MIGRATION = Path(__file__).resolve().parents[4] / "src/api/langboard/migrations/versions/20261004180159-814f01ba3dd1.py"
RETRY_MIGRATION = (
    Path(__file__).resolve().parents[4] / "src/api/langboard/migrations/versions/20261004181756-0cc6abc4b020.py"
)


def test_activity_fanout_migration_keeps_historical_rows_ineligible_and_downgrades() -> None:
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    metadata = MetaData()
    board = Table("project_activity", metadata, Column("id", BigInteger, primary_key=True))
    wiki = Table("project_wiki_activity", metadata, Column("id", BigInteger, primary_key=True))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(board.insert().values(id=1))
        connection.execute(wiki.insert().values(id=2))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        reflected_board = Table(board.name, MetaData(), autoload_with=connection)
        reflected_wiki = Table(wiki.name, MetaData(), autoload_with=connection)
        assert connection.execute(select(reflected_board.c.email_fanout_pending)).scalar_one() is None
        assert connection.execute(select(reflected_wiki.c.email_fanout_pending)).scalar_one() is None
        assert "ix_project_activity_email_fanout_pending" in {
            index["name"] for index in inspect(connection).get_indexes(board.name)
        }
        assert "ix_project_wiki_activity_email_fanout_pending" in {
            index["name"] for index in inspect(connection).get_indexes(wiki.name)
        }

        migration.downgrade()
        assert "email_fanout_pending" not in {column["name"] for column in inspect(connection).get_columns(board.name)}
        assert "email_fanout_pending" not in {column["name"] for column in inspect(connection).get_columns(wiki.name)}
    engine.dispose()


def test_fanout_retry_migration_preserves_existing_rows_and_downgrades() -> None:
    spec = importlib.util.spec_from_file_location(RETRY_MIGRATION.stem, RETRY_MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    metadata = MetaData()
    board = Table("project_activity", metadata, Column("id", BigInteger, primary_key=True))
    wiki = Table("project_wiki_activity", metadata, Column("id", BigInteger, primary_key=True))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(board.insert().values(id=1))
        connection.execute(wiki.insert().values(id=2))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        for table in (board, wiki):
            reflected = Table(table.name, MetaData(), autoload_with=connection)
            assert connection.execute(select(reflected.c.email_fanout_retry_at)).scalar_one() is None

        migration.downgrade()
        for table in (board, wiki):
            assert "email_fanout_retry_at" not in {
                column["name"] for column in inspect(connection).get_columns(table.name)
            }
    engine.dispose()
