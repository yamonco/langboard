"""Immutable card-author migration proof."""

import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_card_author_migration_backfills_first_creator_and_leaves_unknown_fail_closed() -> None:
    """Existing creators survive, while cards without durable creation evidence remain unowned."""

    path = Path(__file__).resolve().parents[2] / "langboard/migrations/versions/20260908170000-82cd7e14a3f9.py"
    spec = importlib.util.spec_from_file_location("card_author_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE card (id BIGINT PRIMARY KEY, title TEXT NOT NULL)"))
            connection.execute(
                sa.text(
                    "CREATE TABLE project_activity ("
                    "id BIGINT PRIMARY KEY, card_id BIGINT, activity_type TEXT, user_id BIGINT, bot_id BIGINT, created_at TEXT)"
                )
            )
            connection.execute(sa.text("INSERT INTO card VALUES (1, 'User'), (2, 'Bot'), (3, 'Unknown')"))
            connection.execute(
                sa.text(
                    "INSERT INTO project_activity VALUES "
                    "(11, 1, 'card_created', 7, NULL, '2026-01-01'), "
                    "(12, 1, 'card_updated', 8, NULL, '2026-01-02'), "
                    "(21, 2, 'card_created', NULL, 9, '2026-01-01')"
                )
            )
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

            assert connection.execute(
                sa.text("SELECT id, created_by_user_id, created_by_bot_id FROM card ORDER BY id")
            ).all() == [(1, 7, None), (2, None, 9), (3, None, None)]
    finally:
        engine.dispose()
