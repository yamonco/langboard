"""Regression contract for the optional webhook event allowlist column."""

import importlib.util
from pathlib import Path
from types import ModuleType
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260807213000-b8e42f0c9a31.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("webhook_event_allowlist", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_webhook_event_allowlist_migration_is_nullable_and_idempotent() -> None:
    """Upgrade and downgrade can be repeated without changing legacy all-event rows."""

    migration = _migration()
    metadata = sa.MetaData()
    webhook_setting = sa.Table(
        "webhook_setting",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(webhook_setting.insert().values(id=1, name="Legacy"))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("webhook_setting")}
        legacy_events = connection.execute(sa.text("SELECT events FROM webhook_setting WHERE id = 1")).scalar_one()

        assert columns["events"]["nullable"] is True
        assert legacy_events is None

        migration.downgrade()
        migration.downgrade()
        assert "events" not in {column["name"] for column in sa.inspect(connection).get_columns("webhook_setting")}
