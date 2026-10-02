import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_column_locale_migration_preserves_legacy_and_refuses_data_loss():
    path = Path(__file__).parents[2] / "langboard/migrations/versions/20261003190000-2f8c4d0e9a61.py"
    spec = importlib.util.spec_from_file_location("column_locale_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE project_column (id INTEGER PRIMARY KEY,name TEXT NOT NULL)"))
        connection.execute(sa.text("INSERT INTO project_column VALUES (1,'Queue')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.execute(sa.text("SELECT name,translations FROM project_column")).one() == ("Queue", "{}")
        connection.execute(
            sa.text("UPDATE project_column SET translations = :value"), {"value": '{"ko":{"name":"대기"}}'}
        )
        with pytest.raises(RuntimeError, match="Preserve column translations"):
            module.downgrade()
        connection.execute(sa.text("UPDATE project_column SET translations = '{}'"))
        module.downgrade()
        assert connection.execute(sa.text("SELECT name FROM project_column")).scalar() == "Queue"
    engine.dispose()
