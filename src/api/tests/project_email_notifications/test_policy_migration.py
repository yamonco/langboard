"""Migration proof for board SMTP policy and SI defaults."""

import importlib.util
from pathlib import Path
from types import ModuleType
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "src/api/langboard/migrations/versions/20260820090000-3b1a0c5d7e9f.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("project_email_notification_policy", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_policy_storage_and_si_review_default() -> None:
    migration = _migration()
    metadata = sa.MetaData()
    user = sa.Table("user", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    project = sa.Table("project", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    template = sa.Table(
        "project_template",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(user.insert().values(id=1))
        connection.execute(project.insert().values(id=1))
        connection.execute(template.insert().values(id=1, name="SI"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        reflected = sa.Table("project_template", sa.MetaData(), autoload_with=connection)
        policy = connection.execute(sa.select(reflected.c.email_notification_policy)).scalar_one()
        tables = set(sa.inspect(connection).get_table_names())

    assert policy == migration.SI_EMAIL_NOTIFICATION_POLICY
    assert "project_email_notification_policy" in tables
    assert "project_email_notification_recipient" in tables
